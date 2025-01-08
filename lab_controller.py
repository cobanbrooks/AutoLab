import os
import sys
import yaml
import git
import json
import time
import logging
import hashlib
import subprocess
import pandas as pd
from enum import Enum
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Status Tracking
class LabState(Enum):
    IDLE = "Waiting for new sequence"
    SEQUENCE_RECEIVED = "New sequence received, generating instructions"
    EXPERIMENTING = "Robot performing DNA assembly, amplification, expression, assay"
    PROCESSING = "Processing plate data"
    ERROR = "Error encountered"

class LabStatus:
    def __init__(self, repo_path, status_file='lab_status.json'):
        self.status_file = os.path.join(repo_path, status_file)
        self.repo = git.Repo(repo_path)
        self.state = LabState.IDLE
        self.current_step = None
        self.error = None
        
    def update_state(self, state: LabState, step_details: str = None, error: str = None):
        """Update the lab's current state and push to GitHub"""
        self.state = state
        self.current_step = step_details
        self.error = error
        self._write_and_push_status()
    
    def get_status(self):
        """Get current status"""
        return {
            'state': self.state.value,
            'current_step': self.current_step,
            'error': self.error,
            'last_updated': datetime.now().isoformat()
        }
    
    def _write_and_push_status(self):
        """Write status to file and push to GitHub"""
        try:
            with open(self.status_file, 'w') as f:
                json.dump(self.get_status(), f, indent=2)
            
            self.repo.index.add([os.path.basename(self.status_file)])
            self.repo.index.commit('Update lab status')
            self.repo.remotes.origin.push()
        except Exception as e:
            print(f"Error updating status: {e}")

class PlateDataHandler(FileSystemEventHandler):
    def __init__(self, repo_path, input_file, output_file, status):
        self.repo_path = repo_path
        self.input_file = input_file
        self.output_file = output_file
        self.repo = git.Repo(repo_path)
        self.logger = logging.getLogger('lab_automation')
        self.status = status
        self.last_processed_hash = None

    def get_file_hash(self, filepath):
        with open(filepath, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
        
    def on_modified(self, event):
        if event.src_path.endswith(self.input_file):
            #checks if content of the file changed
            current_hash = self.get_file_hash(event.src_path)
            if current_hash == self.last_processed_hash:
                return
            
            self.logger.info("Plate data modified, processing...")
            self.status.update_state(LabState.PROCESSING, "Processing plate data")
            self.process_and_push()
            self.last_processed_hash = current_hash
            
    def process_and_push(self):
        try:
            # Process plate data
            subprocess.run(['python', 'process_plate_data.py',
                        '--input', self.input_file,
                        '--output', self.output_file], check=True)
            
            # Update DNA inventory CSV
            dna_tracker = DNATracker()
            dna_tracker.export_to_csv()
            
            # Push to GitHub
            self.repo.index.add([
                self.output_file,
                'dna_inventory.csv',
                'dna_inventory.json'
            ])
            self.repo.index.commit('Update processed plate data and DNA inventory')
            self.repo.remotes.origin.push()
            self.logger.info("Processed data and DNA inventory pushed to GitHub")
            self.status.update_state(LabState.IDLE, "Processing complete") 

        except Exception as e:
            self.logger.error(f"Error processing plate data: {e}")

class DNATracker:
    def __init__(self, inventory_file='dna_inventory.json'):
        self.inventory_file = inventory_file
        self.inventory = self.load_inventory()
        
    def load_inventory(self):
        """Load or initialize DNA fragment inventory"""
        try:
            with open(self.inventory_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            # Initialize with 48 fragments, 200µL each
            inventory = {}
            for p in range(1, 7):  # 6 parents
                for f in range(8):  # 8 fragments each
                    fragment_id = f"p{p}f{f}"
                    # Format well as "A01", "B01", etc.
                    row = chr(66 + (p-1))  # B + offset
                    col = str(f + 3).zfill(2)  # Start at 03
                    well = f"{row}{col}"
                    
                    inventory[fragment_id] = {
                        "well": well,
                        "volume": 200,  # Initial volume in µL
                        "history": []
                    }
            
            self.save_inventory(inventory)
            return inventory
            
    def save_inventory(self, inventory=None):
        """Save current inventory state"""
        if inventory is None:
            inventory = self.inventory
        with open(self.inventory_file, 'w') as f:
            json.dump(inventory, f, indent=2)
            
    def get_well_formats(self, well):
        """Convert between A01 and A1 formats to ensure matching"""
        row = well[0]
        col = well[1:]
        return [well, f"{row}{int(col)}", f"{row}{int(col):02d}"]

    def update_volumes(self, worklist_file):
        """Update volumes based on worklist"""
        df = pd.read_csv(worklist_file)

        # Track all updates for this run
        updates = []
        timestamp = datetime.now().isoformat()
        
        for _, row in df.iterrows():
            well = row['Source_Well']
            volume_used = float(row['Volume'])
            well_formats = self.get_well_formats(well)
            
            # Find fragment id from well
            fragment_id = None
            for fid, data in self.inventory.items():
                if data['well'] in well_formats:
                    fragment_id = fid
                    break
            
            if fragment_id:
                # Update volume
                current_vol = self.inventory[fragment_id]['volume']
                new_vol = current_vol - volume_used
                
                # Record the update
                update = {
                    'timestamp': timestamp,
                    'volume_used': volume_used,
                    'volume_remaining': new_vol
                }
                
                self.inventory[fragment_id]['volume'] = new_vol
                self.inventory[fragment_id]['history'].append(update)
                
                updates.append({
                    'fragment': fragment_id,
                    'well': well,
                    'volume_used': volume_used,
                    'volume_remaining': new_vol
                })
            else:
                print(f"No matching fragment found for well {well}")
        
        # Save updated inventory
        self.save_inventory()
        return updates
        
    def export_to_csv(self, filename='dna_inventory.csv'):
        """Export current inventory to CSV"""
        rows = []
        for fid, data in self.inventory.items():
            rows.append({
                'Fragment_ID': fid,
                'Well': data['well'],
                'Volume_Remaining': data['volume'],
                'Last_Updated': data['history'][-1]['timestamp'] if data['history'] else 'Never'
            })
            
        df = pd.DataFrame(rows)
        df.to_csv(filename, index=False)

    def refill_dna(self, fragment_id=None, well=None, volume_added=200):
        """
        Refill DNA fragment wells with specified volume
        Can use either fragment_id (e.g., 'p1f0') or well location (e.g., 'A01')
        """
        timestamp = datetime.now().isoformat()
        updates = []

        # Handle single refill
        if fragment_id or well:
            if fragment_id and fragment_id in self.inventory:
                target = fragment_id
            else:
                # Find fragment_id from well
                well_formats = self.get_well_formats(well)
                target = None
                for fid, data in self.inventory.items():
                    if data['well'] in well_formats:
                        target = fid
                        break
            
            if target:
                current_vol = self.inventory[target]['volume']
                new_vol = current_vol + volume_added
                
                # Record the update
                self.inventory[target]['volume'] = new_vol
                self.inventory[target]['history'].append({
                    'timestamp': timestamp,
                    'volume_added': volume_added,
                    'volume_total': new_vol
                })
                
                updates.append({
                    'fragment': target,
                    'well': self.inventory[target]['well'],
                    'volume_added': volume_added,
                    'volume_total': new_vol
                })
                print(f"Refilled {target} with {volume_added}µL. New total: {new_vol}µL")
            else:
                print(f"No matching fragment found for {fragment_id or well}")
        
        self.save_inventory()
        return updates
    
    def print_inventory_report(self):
        """Print current inventory status"""
        print("\nDNA Fragment Inventory Report")
        print("=" * 50)
        print(f"{'Fragment':<10} {'Well':<8} {'Volume (µL)':<12} {'Status':<10}")
        print("-" * 50)
        
        for fid, data in sorted(self.inventory.items()):
            status = "LOW" if data['volume'] < 50 else "OK"
            print(f"{fid:<10} {data['well']:<8} {data['volume']:<12.1f} {status:<10}")
            
        print("=" * 50)

class RgntTracker:
    def __init__(self, inventory_file='reagent_inventory.json'):
        self.inventory_file = inventory_file
        self.inventory = self.load_inventory()

    def load_inventory(self):
        """Load or initialize reagent inventory"""
        try:
            with open(self.inventory_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:

            reagents = [
                "GGMM",
                "Primers",
                "PCRMM",
                "E. coli extract",
                "TXTLMM",
                "Water"
            ]

            inventory = {}
            wells = []
            for p in range(1,3):
                for f in range(1,4):
                    row = chr(68 + (p-1))
                    col = str(f + 5).zfill(2)
                    well = f"{row}{col}"
                    wells.append(well)

        for well, reagent in zip(wells, reagents):
            reagent_id = reagent
            inventory[reagent_id] = {
                "well": well,
                "volume": 1000, # Initial vol in uL
                "history": []
            }

            self.save_inventory(inventory)
            return inventory

            
    def save_inventory(self, inventory=None):
        """Save current inventory state"""
        if inventory is None:
            inventory = self.inventory
        with open(self.inventory_file, 'w') as f:
            json.dump(inventory, f, indent=2)
            
    def get_well_formats(self, well):
        """Convert between A01 and A1 formats to ensure matching"""
        row = well[0]
        col = well[1:]
        return [well, f"{row}{int(col)}", f"{row}{int(col):02d}"]

    def update_volumes(self, worklist_file):
        """Update volumes based on worklist"""
        df = pd.read_csv(worklist_file)

        # Track all updates for this run
        updates = []
        timestamp = datetime.now().isoformat()
        
        for _, row in df.iterrows():
            well = row['Source_Well']
            volume_used = float(row['Volume'])
            well_formats = self.get_well_formats(well)
            
            # Find reagent id from well
            reagent_id = None
            for rid, data in self.inventory.items():
                if data['well'] in well_formats:
                    reagent_id = rid
                    break
            
            if reagent_id:
                # Update volume
                current_vol = self.inventory[reagent_id]['volume']
                new_vol = current_vol - volume_used
                
                # Record the update
                update = {
                    'timestamp': timestamp,
                    'volume_used': volume_used,
                    'volume_remaining': new_vol
                }
                
                self.inventory[reagent_id]['volume'] = new_vol
                self.inventory[reagent_id]['history'].append(update)
                
                updates.append({
                    'reagent': reagent_id,
                    'well': well,
                    'volume_used': volume_used,
                    'volume_remaining': new_vol
                })
            else:
                print(f"No matching reagent found for well {well}")
        
        # Save updated inventory
        self.save_inventory()
        return updates
        
    def export_to_csv(self, filename='reagent_inventory.csv'):
        """Export current inventory to CSV"""
        rows = []
        for rid, data in self.inventory.items():
            rows.append({
                'Reagent_ID': rid,
                'Well': data['well'],
                'Volume_Remaining': data['volume'],
                'Last_Updated': data['history'][-1]['timestamp'] if data['history'] else 'Never'
            })
            
        df = pd.DataFrame(rows)
        df.to_csv(filename, index=False)

    def refill_reagent(self, reagent_id=None, well=None, volume_added=200):
        """
        Refill DNA fragment wells with specified volume
        Can use either reagent_id (e.g., 'GGMM') or well location (e.g., 'D05')
        """
        timestamp = datetime.now().isoformat()
        updates = []

        # Handle single refill
        if reagent_id or well:
            if reagent_id and reagent_id in self.inventory:
                target = reagent_id
            else:
                # Find reagent_id from well
                well_formats = self.get_well_formats(well)
                target = None
                for rid, data in self.inventory.items():
                    if data['well'] in well_formats:
                        target = rid
                        break
            
            if target:
                current_vol = self.inventory[target]['volume']
                new_vol = current_vol + volume_added
                
                # Record the update
                self.inventory[target]['volume'] = new_vol
                self.inventory[target]['history'].append({
                    'timestamp': timestamp,
                    'volume_added': volume_added,
                    'volume_total': new_vol
                })
                
                updates.append({
                    'reagent': target,
                    'well': self.inventory[target]['well'],
                    'volume_added': volume_added,
                    'volume_total': new_vol
                })
                print(f"Refilled {target} with {volume_added}µL. New total: {new_vol}µL")
            else:
                print(f"No matching reagent found for {reagent_id or well}")
        
        self.save_inventory()
        return updates
    
    def print_inventory_report(self):
        """Print current inventory status"""
        print("\nReagent Inventory Report")
        print("=" * 50)
        print(f"{'Reagent':<10} {'Well':<8} {'Volume (µL)':<12} {'Status':<10}")
        print("-" * 50)
        
        for rid, data in sorted(self.inventory.items()):
            status = "LOW" if data['volume'] < 50 else "OK"
            print(f"{rid:<10} {data['well']:<8} {data['volume']:<12.1f} {status:<10}")
            
        print("=" * 50)

class LabController:
    def __init__(self, config_path):
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler(), logging.FileHandler('lab_controller.log')]
        )
        self.logger = logging.getLogger('lab_controller')
        
        # Load config
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
            
        self.repo = git.Repo(self.config['repo_path'])
        self.sequence_hash = None
        self.status = LabStatus(self.config['repo_path'])
        
    def check_sequence_updates(self):
        """Check for updates to sequence_query.txt on GitHub"""
        try:
            self.repo.remotes.origin.fetch()
            self.repo.remotes.origin.pull()
            
            with open(os.path.join(self.config['repo_path'], 'sequence_query.txt'), 'rb') as f:
                current_hash = hashlib.md5(f.read()).hexdigest()
                
            if current_hash != self.sequence_hash:
                self.sequence_hash = current_hash
                return True
        except Exception as e:
            self.logger.error(f"Error checking sequence updates: {e}")
        return False
    
    def generate_lab_files(self):
        """Generate worklist and plate layout files"""
        try:
            # Generate pipetting worklist
            subprocess.run([
                'python', 'seq_to_pipetting_steps.py',
                'sequence_query.txt',
                'sequence_segments.csv',
                'output'
            ], check=True)

            # Update DNA volumes
            dna_tracker = DNATracker()
            updates = dna_tracker.update_volumes('output/fragment_assembly_worklist.csv')

            # Log volume updates
            self.logger.info("Updated DNA volumes")
            for update in updates:
                self.logger.info(
                    f"Fragment {update['fragment']} in well {update['well']}: "
                    f"used {update['volume_used']}µL, {update['volume_remaining']}µL remaining"
            )
            
            # Generate plate layout
            subprocess.run([
                'python', 'generate_assay_plate.py',
                'sequence_query.txt',
                'sequence_segments.csv',
                'plate_layout.json'
            ], check=True)
            
            self.logger.info("Generated worklist and plate layout")
            return True
            
        except Exception as e:
            self.logger.error(f"Error generating lab files: {e}")
            return False
            
    def start_plate_monitoring(self):
        """Start monitoring plate_data.csv for changes"""
        handler = PlateDataHandler(
            self.config['repo_path'],
            'plate_data.csv',
            'processed_plate_data.csv',
            self.status
        )
        
        observer = Observer()
        observer.schedule(handler, self.config['repo_path'], recursive=False)
        observer.start()
        return observer
        
    def run(self):
        self.logger.info("Starting lab automation system")
        self.status.update_state(LabState.IDLE)
        observer = None
        
        try:
            while True:
                # Check for sequence updates
                if self.check_sequence_updates():
                    self.logger.info("New sequence detected")
                    self.status.update_state(LabState.SEQUENCE_RECEIVED)
                    
                    # Stop existing monitoring if active
                    if observer:
                        observer.stop()
                        observer.join()
                    
                    # Generate new lab files
                    if self.generate_lab_files():
                        self.status.update_state(LabState.EXPERIMENTING)
                        # Start monitoring plate data
                        observer = self.start_plate_monitoring()
                        
                time.sleep(self.config.get('poll_interval', 60))
                
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            self.status.update_state(LabState.IDLE, "Shutdown complete")
            if observer:
                observer.stop()
                observer.join()
        except Exception as e:
            self.status.update_state(LabState.ERROR, error=str(e))
            self.logger.error(f"Error: {e}")

    
if __name__ == "__main__":
    # Default configuration
    default_config = {
        'repo_path': '/path/to/repo',
        'poll_interval': 60  # seconds
    }
    
    config_path = 'lab_config.yml'
    if not os.path.exists(config_path):
        with open(config_path, 'w') as f:
            yaml.dump(default_config, f)
        print(f"Created default config at {config_path}")
        exit(1)
        
    automation = LabController(config_path)
    automation.run()