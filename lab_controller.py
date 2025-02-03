import os
import sys
import yaml
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
from data_transfer import SFTPTransfer

# Status Tracking
class LabState(Enum):
    IDLE = "Waiting for new sequence"
    SEQUENCE_RECEIVED = "New sequence received, generating instructions"
    EXPERIMENTING = "Robot performing DNA assembly, amplification, expression, assay"
    PROCESSING = "Processing plate data"
    ERROR = "Error encountered"

class PlateDataHandler(FileSystemEventHandler):
    def __init__(self, data_dir: str, input_filename: str, output_filename: str, controller=None):
        self.data_dir = data_dir
        self.input_filename = input_filename
        self.output_filename = output_filename
        self.logger = logging.getLogger('lab_automation')
        self.last_processed_hash = None
        self.transfer = SFTPTransfer()
        self.controller = controller

        # Log initialization
        self.logger.info(f"Initialized PlateDataHandler:")
        self.logger.info(f"  data_dir: {data_dir}")
        self.logger.info(f"  input_file: {input_filename}")
        self.logger.info(f"  output_file: {output_filename}")

    def get_file_hash(self, filepath):
        with open(filepath, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    def process_and_transfer(self):
        """Process plate data and transfer to GPU server"""
        try:
            # Process the data
            input_path = os.path.join(self.data_dir, self.input_filename)
            output_path = os.path.join(self.data_dir, self.output_filename)
            
            subprocess.run([
                'python', 'process_plate_data.py',
                '--input', input_path,
                '--output', output_path
            ], check=True)
            
            # Transfer to GPU server
            if self.transfer.connect():
                self.transfer.transfer_file(output_path)
                self.transfer.close()
                self.logger.info("Processed data and transferred to GPU server")

                # Stop plate monitoring and restart sequence monitoring
                if self.controller:
                    if self.controller.plate_observer:
                        self.controller.plate_observer.stop()
                        self.controller.plate_observer = None
                    self.controller.start_sequence_monitoring()
                return True
            else:
                self.logger.error("Failed to connect to GPU server")
                return False
                
                
        except Exception as e:
            self.logger.error(f"Error processing/transferring data: {e}")

    def on_modified(self, event):
        if event.src_path.endswith(self.input_filename):
            current_hash = self.get_file_hash(event.src_path)
            if current_hash == self.last_processed_hash:
                return
            
            self.logger.info("Plate data modified, processing...")
            self.process_and_transfer()
            self.last_processed_hash = current_hash


class DNATracker:
    def __init__(self, inventory_dir='inventories'):
        self.inventory_dir = inventory_dir
        self.inventory_file = os.path.join(inventory_dir,'dna_inventory.json')
        os.makedirs(inventory_dir,exist_ok=True)
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
        
    def export_to_csv(self):
        """Export current inventory to CSV"""
        csv_path = os.path.join(self.inventory_dir, 'dna_inventory.csv')
        rows = []
        for fid, data in self.inventory.items():
            rows.append({
                'Fragment_ID': fid,
                'Well': data['well'],
                'Volume_Remaining': data['volume'],
                'Last_Updated': data['history'][-1]['timestamp'] if data['history'] else 'Never'
            })
            
        df = pd.DataFrame(rows)
        df.to_csv(csv_path, index=False)

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
    def __init__(self, inventory_dir='inventories'):
        self.inventory_dir = inventory_dir
        self.inventory_file = os.path.join(inventory_dir, 'reagent_inventory.json')
        os.makedirs(inventory_dir, exist_ok=True)
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
        """Update volumes based on worklist, only for Reagents source plate"""
        df = pd.read_csv(worklist_file)


        # Track all updates for this run
        updates = []
        timestamp = datetime.now().isoformat()
        
        # Filter for only Reagents source plate
        reagents_df = df[df['Source_Plate'] == 'Reagents']
        
        for _, row in reagents_df.iterrows():
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
        
    def export_to_csv(self):
        """Export current inventory to CSV"""
        csv_path = os.path.join(self.inventory_dir, 'reagent_inventory.csv')
        rows = []
        for rid, data in self.inventory.items():
            rows.append({
                'Reagent_ID': rid,
                'Well': data['well'],
                'Volume_Remaining': data['volume'],
                'Last_Updated': data['history'][-1]['timestamp'] if data['history'] else 'Never'
            })
            
        df = pd.DataFrame(rows)
        df.to_csv(csv_path, index=False)

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
        self.status = LabState.IDLE
        self.sequence_observer = None
        self.plate_observer = None

    class SequenceHandler(FileSystemEventHandler):
        def __init__(self, controller):
            self.controller = controller
            self.sequence_file = os.path.join(
            self.controller.config['paths']['data_dir'],
            self.controller.config['files']['sequence_query']
        )
            
        def on_modified(self, event):
            if event.src_path.endswith(self.sequence_file):
                self.controller.logger.info("New sequence detected")
                self.controller.status = LabState.SEQUENCE_RECEIVED
                if self.controller.generate_lab_files():
                    self.controller.status = LabState.EXPERIMENTING
                    self.controller.start_plate_monitoring()

    def start_sequence_monitoring(self):
        handler = self.SequenceHandler(self)
        self.sequence_observer = Observer()
        self.sequence_observer.schedule(handler, self.config['paths']['data_dir'])
        self.sequence_observer.start()

    def start_plate_monitoring(self):
        """Start monitoring plate_data.csv for changes"""
        if self.plate_observer:
            self.plate_observer.stop()
            self.plate_observer.join()

        handler = PlateDataHandler(
            self.config['paths']['data_dir'],
            self.config['files']['plate_data'],
            self.config['files']['processed_data'],
            controller=self
        )
        
        self.plate_observer = Observer()
        self.plate_observer.schedule(handler, self.config['paths']['data_dir'], recursive=False)
        self.plate_observer.start()
        self.logger.info("Started plate data monitoring")



    def generate_lab_files(self):
        """Generate worklist and plate layout files"""
        try:
            # Generate pipetting worklist
            subprocess.run([
                'python', 'seq_to_pipetting_steps.py',
                os.path.join(self.config['paths']['data_dir'], 'sequence_query.txt'),
                os.path.join(self.config['paths']['data_dir'], 'sequence_segments.csv'), 
                self.config['paths']['worklists_dir']
            ], check=True)


            # Initialize trackers
            inventory_dir = os.path.join(self.config['paths']['inventory_dir'])
            dna_tracker = DNATracker(inventory_dir)
            rgnt_tracker = RgntTracker(inventory_dir)

            # Update DNA volumes
            updates_dna = dna_tracker.update_volumes('worklists/fragment_assembly_worklist.csv')

            # Update reagent volumes from all worklists
            worklist_files = [
                'worklists/GGMM_Wklist.csv',
                'worklists/PrimerTransfer_Wklist.csv',
                'worklists/PCRMM_Transfer_Wklist.csv',
                'worklists/PCR_product_dilution_Wklist.csv',
                'worklists/TXTL_Wklist.csv'
            ]
            
            rgnt_updates = []
            for worklist_file in worklist_files:
                updates = rgnt_tracker.update_volumes(worklist_file)
                rgnt_updates.extend(updates)

            # Log volume updates
            self.logger.info("Updated DNA volumes")
            for update in updates_dna:
                self.logger.info(
                    f"Fragment {update['fragment']} in well {update['well']}: "
                    f"used {update['volume_used']}µL, {update['volume_remaining']}µL remaining"
                )
                
            self.logger.info("Updated reagent volumes")
            for update in rgnt_updates:
                self.logger.info(
                    f"Reagent {update['reagent']} in well {update['well']}: "
                    f"used {update['volume_used']}µL, {update['volume_remaining']}µL remaining"
                )
            
            # Generate plate layout
            subprocess.run([
                'python', 'generate_assay_plate.py',
                os.path.join(self.config['paths']['data_dir'], 'sequence_query.txt'),
                os.path.join(self.config['paths']['data_dir'], 'sequence_segments.csv'), 
                'plate_layout.json'
            ], check=True)
            
            self.logger.info("Generated worklist and plate layout")
            self.sequence_observer.stop() #here
            return True
            
        except Exception as e:
            self.logger.error(f"Error generating lab files: {e}")
            return False
    '''      
    def start_plate_monitoring(self):
        """Start monitoring plate_data.csv for changes"""

        if self.plate_observer:
            self.plate_observer.stop()
            self.plate_observer.join()

        handler = PlateDataHandler(
            self.config['paths']['data_dir'],
            self.config['files']['plate_data'],
            self.config['files']['processed_data']
        )
        
        self.plate_observer = Observer()
        self.plate_observer.schedule(handler, self.config['paths']['data_dir'], recursive=False)
        self.plate_observer.start()
        '''
        
    def run(self):
        self.logger.info("Starting lab automation system")
        try:
            self.start_sequence_monitoring()
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Shutting down...")
            if self.sequence_observer:
                self.sequence_observer.stop()
                self.sequence_observer.join()
            if self.plate_observer:
                self.plate_observer.stop()
                self.plate_observer.join()
        except Exception as e:
            self.status = LabState.ERROR
            self.logger.error(f"Error: {e}")
    
if __name__ == "__main__":
    config_path = os.path.join('configs', 'lab_config.yml')
    
    # Create default config if it doesn't exist
    if not os.path.exists(config_path):
        default_config = {
            'paths': {
                'data_dir': "data",
                'worklists_dir': "worklists",
                'inventory_dir': "inventories",
                'logs_dir': "logs"
            },
            'files': {
                'plate_data': "plate_data.csv",
                'processed_data': "processed_plate_data.csv",
                'sequence_query': "sequence_query.txt",
                'sequence_segments': "sequence_segments.csv"
            },
            'sftp': {
                'hostname': "coltrane.egr.duke.edu",
                'username': "cb643",
                'remote_path': "/home/cb643",
                'key_filename': "/Users/cobanbrooks/.ssh/id_rsa",
                'port': 22
            }
        }
        
        # Create worklists directory if it doesn't exist
        os.makedirs(default_config['paths']['worklists_dir'], exist_ok=True)
        
        with open(config_path, 'w') as f:
            yaml.dump(default_config, f, default_flow_style=False)
        print(f"Created default config at {config_path}")
        print("Please edit the config file with your settings before running again.")
        exit(1)
    
    try:    
        automation = LabController(config_path)
        automation.run()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    except Exception as e:
        print(f"Fatal error: {e}")
        exit(1)