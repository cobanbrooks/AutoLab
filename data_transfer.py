import os
import paramiko
import logging
from pathlib import Path
import yaml

class SFTPTransfer:
    def __init__(self, config_path='configs/lab_config.yml'):
        # Setup logging
        self.logger = logging.getLogger('data_transfer')
        
        # Load config
        self.config = self._load_config(config_path)
        
        # Initialize SSH client
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
    def _load_config(self, config_path):
        """Load SFTP configuration"""
        if not os.path.exists(config_path):
            config = {
                'sftp': {
                    'hostname': 'coltrane.egr.duke.edu',
                    'username': 'cb643',
                    'remote_path': '/home/cb643/self_driving/data/plate_data',
                    'key_filename': '/Users/cobanbrooks/.ssh/id_rsa',
                    'port': 22
                }
            }
            with open(config_path, 'w') as f:
                yaml.dump(config, f)
            raise FileNotFoundError(f"Created default config at {config_path}. Please edit before running.")
            
        with open(config_path) as f:
            return yaml.safe_load(f)
    
    def connect(self):
        """Establish SFTP connection"""
        try:
            cfg = self.config['sftp']
            self.ssh.connect(
                hostname=cfg['hostname'],
                username=cfg['username'],
                key_filename=os.path.expanduser(cfg['key_filename']),
                port=cfg['port']
            )
            self.sftp = self.ssh.open_sftp()
            self.logger.info(f"Connected to {cfg['hostname']}")
            return True
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            return False
        
    def transfer_file(self, local_path, remote_filename=None):
        """Transfer a file to GPU server"""
        try:
            if not os.path.exists(local_path):
                self.logger.error(f"Local file does not exist: {local_path}")
                return False  # Stop here if the file doesn't exist

            if not remote_filename:
                remote_filename = os.path.basename(local_path)
                    
            remote_path = os.path.join(
                self.config['sftp']['remote_path'],
                remote_filename
            )
            
            self.logger.info(f"Attempting transfer: {local_path} → {remote_path}")
            self.sftp.put(local_path, remote_path, callback=None, confirm=False)
            self.logger.info(f"Transferred {local_path} to {remote_path}")
            return True
                
        except Exception as e:
            self.logger.error(f"Transfer failed: {e}")
            return False

            
    def close(self):
        """Close SFTP connection"""
        if hasattr(self, 'sftp'):
            self.sftp.close()
        self.ssh.close()