import os
import time
import signal
from git import Repo
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import datetime
import hashlib
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import yaml
import subprocess
from typing import Optional
from pathlib import Path

class EmailNotifier:
    def __init__(self, config):
        self.config = config['email']
        self.logger = logging.getLogger('plate_processor.email')
        
    def send_email(self, subject: str, body: str, priority: str = 'normal'):
        try:
            msg = MIMEMultipart()
            msg['From'] = self.config['from_address']
            msg['To'] = self.config['to_address']
            msg['Subject'] = f"[Plate Processor] {subject}"
            
            if priority == 'high':
                msg['X-Priority'] = '1'
            
            msg.attach(MIMEText(body, 'plain'))
            
            with smtplib.SMTP(self.config['smtp_server'], self.config['smtp_port']) as server:
                if self.config.get('use_tls', True):
                    server.starttls()
                server.login(self.config['username'], self.config['password'])
                server.send_message(msg)
                
            self.logger.info(f"Email sent: {subject}")
        except Exception as e:
            self.logger.error(f"Failed to send email: {str(e)}")

class ExternalProcessor:
    """Calls external script to process the data"""
    
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
    
    def process_plate_data(self, input_file: str, output_file: str) -> bool:
        try:
            self.logger.info(f"Processing {input_file} to {output_file}")
            
            # Get the processing script path from config
            script_path = self.config['processing']['script_path']
            
            # Check if it's a Python script or shell script
            if script_path.endswith('.py'):
                # Run Python script
                result = subprocess.run([
                    'python',
                    script_path,
                    '--input', input_file,
                    '--output', output_file
                ], capture_output=True, text=True)
            else:
                # Run shell script
                result = subprocess.run([
                    script_path,
                    input_file,
                    output_file
                ], capture_output=True, text=True)
            
            # Check if process was successful
            if result.returncode == 0:
                self.logger.info("Processing completed successfully")
                if result.stdout:
                    self.logger.info(f"Process output: {result.stdout}")
                return True
            else:
                self.logger.error(f"Processing failed with return code {result.returncode}")
                self.logger.error(f"Error output: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error processing data: {str(e)}")
            return False

class PlateDataHandler(FileSystemEventHandler):
    def __init__(self, repo_path: str, input_filename: str, output_filename: str, config: dict):
        self.repo_path = repo_path
        self.repo = Repo(repo_path)
        self.last_input_md5: Optional[str] = None
        self.last_output_md5: Optional[str] = None
        self.logger = logging.getLogger('plate_processor.handler')
        self.processor = ExternalProcessor(config, self.logger)
        self.input_filename = input_filename
        self.output_filename = output_filename
        self.notifier = EmailNotifier(config)
        
    def get_file_md5(self, file_path: str) -> str:
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    
    def on_modified(self, event):
        self.logger.info(f"Detected change in: {event.src_path}")
        
        # Get just the filename without the path
        filename = os.path.basename(event.src_path)
        
        # Check which file changed
        if filename == self.input_filename:
            self.logger.info("Identified as input file change")
            self.handle_input_change(event.src_path)
        elif filename == self.output_filename:
            self.logger.info("Identified as output file change")
            self.handle_output_change(event.src_path)
        else:
            self.logger.info(f"File change ignored - not matching {self.input_filename} or {self.output_filename}")

    
    def handle_input_change(self, input_file_path: str):
        try:
            current_md5 = self.get_file_md5(input_file_path)
            if current_md5 == self.last_input_md5:
                self.logger.info("Input file content unchanged, skipping processing")
                return
                
            self.last_input_md5 = current_md5
            self.logger.info(f"New input file MD5: {current_md5}")
            
            output_file_path = os.path.join(
                os.path.dirname(input_file_path),
                self.output_filename
            )
            
            # Process the data
            self.logger.info("Starting plate data processing...")
            if not self.processor.process_plate_data(input_file_path, output_file_path):
                self.logger.error("Processing failed")
                
        except Exception as e:
            self.logger.error(f"Error in handle_input_change: {str(e)}")

    def handle_output_change(self, output_file_path: str):
        try:
            # Check if output content has actually changed
            current_md5 = self.get_file_md5(output_file_path)
            self.logger.info(f"Output file MD5: {current_md5}")
            self.logger.info(f"Previous output MD5: {self.last_output_md5}")
            
            if current_md5 == self.last_output_md5:
                self.logger.info("Output file content unchanged, skipping git push")
                return
                
            self.last_output_md5 = current_md5
            
            # Get paths relative to repo root
            input_file_path = os.path.join(
                os.path.dirname(output_file_path),
                self.input_filename
            )
            
            self.logger.info(f"Input path: {input_file_path}")
            self.logger.info(f"Output path: {output_file_path}")
            self.logger.info(f"Repo path: {self.repo_path}")
            
            input_relative_path = os.path.relpath(input_file_path, self.repo_path)
            output_relative_path = os.path.relpath(output_file_path, self.repo_path)
            
            self.logger.info(f"Relative input path: {input_relative_path}")
            self.logger.info(f"Relative output path: {output_relative_path}")
            
            # Stage both files
            self.logger.info("Staging files...")
            self.repo.index.add([input_relative_path, output_relative_path])
            
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            commit_message = f"Update plate data and analysis at {timestamp}"
            
            self.logger.info("Creating commit...")
            self.repo.index.commit(commit_message)
            
            self.logger.info("Pushing to remote...")
            origin = self.repo.remote('origin')
            push_info = origin.push()
            
            self.logger.info("Push complete. Push info:")
            for info in push_info:
                self.logger.info(f"  {info.summary}")
            
            success_msg = f"Successfully pushed to GitHub at {timestamp}"
            self.logger.info(success_msg)
            self.notifier.send_email(
                "Plate Data Update",
                f"New plate data has been processed and pushed to GitHub at {timestamp}"
            )
            
        except Exception as e:
            error_msg = f"Error in handle_output_change: {str(e)}"
            self.logger.error(error_msg)
            self.logger.exception("Full traceback:")
            self.notifier.send_email(
                "Error Pushing to GitHub",
                error_msg,
                priority='high'
            )

def setup_logging(log_path: str):
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler()
        ]
    )

def signal_handler(signum, frame):
    logger = logging.getLogger('plate_processor')
    logger.info('Shutting down gracefully...')
    global observer
    observer.stop()
    observer = None

def watch_directory(path: str, input_filename: str, output_filename: str, config: dict):
    global observer
    event_handler = PlateDataHandler(path, input_filename, output_filename, config)
    observer = Observer()
    observer.schedule(event_handler, path, recursive=False)
    
    logger = logging.getLogger('plate_processor')
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info(f"Starting plate data monitor...")
    logger.info(f"Watching for changes to {input_filename}")
    logger.info(f"Will process and save results to {output_filename}")
    
    observer.start()
    
    try:
        while observer is not None:
            time.sleep(1)
    finally:
        if observer is not None:
            observer.stop()
            observer.join()
        logger.info("Monitoring stopped")

def create_default_config(config_path: str):
    if not os.path.exists(config_path):
        default_config = {
            'email': {
                'smtp_server': 'smtp.gmail.com',
                'smtp_port': 587,
                'username': 'your-email@gmail.com',
                'password': 'your-app-password',
                'from_address': 'your-email@gmail.com',
                'to_address': 'recipient@example.com',
                'use_tls': True
            },
            'paths': {
                'repo_path': '/path/to/your/repository',
                'input_filename': 'plate_data.csv',
                'output_filename': 'processed_plate_data.csv',
                'log_file': 'plate_processor.log'
            },
            'processing': {
                'script_path': '/path/to/your/process_plate_data.py'
                # or '/path/to/your/process_plate_data.sh' for shell script
            }
        }
        
        with open(config_path, 'w') as f:
            yaml.dump(default_config, f, default_flow_style=False)
        
        print(f"Created default config file at {config_path}")
        print("Please edit the config file with your settings before running the script.")
        exit(1)

if __name__ == "__main__":
    # Setup configuration
    config_path = 'plate_data_processor_email.yml'
    create_default_config(config_path)
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Setup logging
    setup_logging(config['paths']['log_file'])
    logger = logging.getLogger('plate_processor')
    
    try:
        watch_directory(
            config['paths']['repo_path'],
            config['paths']['input_filename'],
            config['paths']['output_filename'],
            config
        )
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        EmailNotifier(config).send_email(
            "Fatal Error - Plate Processor Stopped",
            f"The plate processor has stopped due to a fatal error: {str(e)}",
            priority='high'
        )
       