#!/usr/bin/env python3
"""
Professional Log Parser

A robust, scalable log parsing utility for extracting specific commands
from system log files with support for multiple compression formats.

Author: m3hr4nn
Version: 2.0.0
License: MIT
"""

import argparse
import bz2
import csv
import gzip
import logging
import os
import re
import socket
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Iterator, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


@dataclass
class LogEntry:
    """Data class representing a parsed log entry."""
    timestamp: str
    command: str
    file_path: str
    log_line: str
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for CSV writing."""
        return asdict(self)


class LogParserConfig:
    """Configuration class for the log parser."""
    
    DEFAULT_LOG_DIR = "/var/log"
    DEFAULT_COMMANDS = ["systemctl", "reboot", "shutdown"]
    SUPPORTED_EXTENSIONS = {".log", ".gz", ".bz2"}
    DATE_PATTERNS = [
        r'\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\b',
        r'\b([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\b',
        r'\b(\d{1,2}/\d{1,2}/\d{4}\s+\d{2}:\d{2}:\d{2})\b'
    ]
    
    def __init__(self, 
                 commands: Optional[List[str]] = None,
                 log_directory: Optional[str] = None,
                 output_file: Optional[str] = None,
                 max_workers: int = 4,
                 chunk_size: int = 8192):
        self.commands = commands or self.DEFAULT_COMMANDS
        self.log_directory = Path(log_directory or self.DEFAULT_LOG_DIR)
        self.output_file = output_file or self._generate_output_filename()
        self.max_workers = max_workers
        self.chunk_size = chunk_size
        self.command_pattern = self._compile_command_pattern()
        self.date_patterns = [re.compile(pattern) for pattern in self.DATE_PATTERNS]
    
    def _generate_output_filename(self) -> str:
        """Generate timestamped output filename."""
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        hostname = socket.gethostname()
        return f"{hostname}_{timestamp}_parsed_logs.csv"
    
    def _compile_command_pattern(self) -> re.Pattern:
        """Compile regex pattern for command matching."""
        escaped_commands = [re.escape(cmd) for cmd in self.commands]
        pattern = r'\b(?:' + '|'.join(escaped_commands) + r')\b'
        return re.compile(pattern, re.IGNORECASE)


class LogFileProcessor:
    """Handles processing of individual log files."""
    
    def __init__(self, config: LogParserConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    def extract_timestamp(self, line: str) -> str:
        """Extract timestamp from log line using multiple patterns."""
        for pattern in self.config.date_patterns:
            match = pattern.search(line)
            if match:
                return match.group(1)
        return ""
    
    def process_line(self, line: str, file_path: str) -> Optional[LogEntry]:
        """Process a single log line and return LogEntry if commands found."""
        try:
            # Check if line contains any of our target commands
            matches = self.config.command_pattern.findall(line)
            if matches:
                return LogEntry(
                    timestamp=self.extract_timestamp(line),
                    command='|'.join(set(matches)), # Remove duplicates
                    file_path=str(file_path),
                    log_line=line.strip()
                )
        except Exception as e:
            self.logger.warning(f"Error processing line in {file_path}: {e}")
        return None
    
    def process_file(self, file_path: Path) -> List[LogEntry]:
        """Process a single log file and return list of matching entries."""
        entries = []
        
        try:
            with self._open_file(file_path) as file_handle:
                for line_num, line in enumerate(file_handle, 1):
                    try:
                        # Handle both bytes and string input
                        if isinstance(line, bytes):
                            line = line.decode('utf-8', errors='ignore')
                        
                        entry = self.process_line(line, file_path)
                        if entry:
                            entries.append(entry)
                            
                    except Exception as e:
                        self.logger.warning(f"Error at line {line_num} in {file_path}: {e}")
                        continue
                        
        except PermissionError:
            self.logger.error(f"Permission denied: {file_path}")
        except Exception as e:
            self.logger.error(f"Error processing file {file_path}: {e}")
        
        return entries
    
    def _open_file(self, file_path: Path):
        """Open file with appropriate handler based on extension."""
        suffix = file_path.suffix.lower()
        
        if suffix == '.gz':
            return gzip.open(file_path, 'rt', encoding='utf-8', errors='ignore')
        elif suffix == '.bz2':
            return bz2.open(file_path, 'rt', encoding='utf-8', errors='ignore')
        else:
            return open(file_path, 'r', encoding='utf-8', errors='ignore')


class LogDiscovery:
    """Handles discovery of log files in the filesystem."""
    
    def __init__(self, config: LogParserConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    def discover_log_files(self) -> List[Path]:
        """Discover all supported log files in the configured directory."""
        log_files = []
        
        if not self.config.log_directory.exists():
            raise FileNotFoundError(f"Log directory does not exist: {self.config.log_directory}")
        
        if not self.config.log_directory.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {self.config.log_directory}")
        
        try:
            for file_path in self.config.log_directory.rglob('*'):
                if (file_path.is_file() and 
                    file_path.suffix.lower() in self.config.SUPPORTED_EXTENSIONS):
                    log_files.append(file_path)
                    
        except PermissionError as e:
            self.logger.warning(f"Permission denied accessing directory: {e}")
        
        self.logger.info(f"Discovered {len(log_files)} log files")
        return log_files


class ProgressTracker:
    """Thread-safe progress tracking for file processing."""
    
    def __init__(self, total_files: int):
        self.total_files = total_files
        self.completed_files = 0
        self.lock = threading.Lock()
        self.start_time = time.time()
    
    def update(self, file_path: str, entries_found: int):
        """Update progress and display current status."""
        with self.lock:
            self.completed_files += 1
            percentage = (self.completed_files / self.total_files) * 100
            elapsed = time.time() - self.start_time
            
            print(f"\r[{self.completed_files:>4}/{self.total_files}] "
                  f"({percentage:5.1f}%) {file_path} - {entries_found} matches found "
                  f"({elapsed:.1f}s)", end='', flush=True)


class LogParser:
    """Main log parser orchestrator."""
    
    def __init__(self, config: LogParserConfig):
        self.config = config
        self.processor = LogFileProcessor(config)
        self.discovery = LogDiscovery(config)
        self.logger = logging.getLogger(__name__)
        
    def parse_logs(self) -> List[LogEntry]:
        """Main parsing method - orchestrates the entire process."""
        self.logger.info("Starting log parsing process")
        
        # Discover log files
        log_files = self.discovery.discover_log_files()
        if not log_files:
            self.logger.warning("No log files found")
            return []
        
        # Process files concurrently
        all_entries = []
        progress = ProgressTracker(len(log_files))
        
        print(f"Processing {len(log_files)} log files using {self.config.max_workers} workers...")
        
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            # Submit all files for processing
            future_to_file = {
                executor.submit(self.processor.process_file, file_path): file_path
                for file_path in log_files
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    entries = future.result()
                    all_entries.extend(entries)
                    progress.update(str(file_path), len(entries))
                except Exception as e:
                    self.logger.error(f"Error processing {file_path}: {e}")
                    progress.update(str(file_path), 0)
        
        print() # New line after progress display
        self.logger.info(f"Parsing complete. Found {len(all_entries)} matching entries")
        return all_entries
    
    def save_results(self, entries: List[LogEntry]):
        """Save results to CSV file."""
        if not entries:
            self.logger.warning("No entries to save")
            return
        
        try:
            with open(self.config.output_file, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['timestamp', 'command', 'file_path', 'log_line']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for entry in entries:
                    writer.writerow(entry.to_dict())
            
            self.logger.info(f"Results saved to: {self.config.output_file}")
            
        except Exception as e:
            self.logger.error(f"Error saving results: {e}")
            raise


class CommandLineInterface:
    """Handles command line argument parsing and user interaction."""
    
    @staticmethod
    def load_commands_from_file(file_path: str) -> List[str]:
        """Load commands from a text file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                commands = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            return commands
        except FileNotFoundError:
            raise FileNotFoundError(f"Command file not found: {file_path}")
        except Exception as e:
            raise Exception(f"Error reading command file: {e}")
    
    @staticmethod
    def setup_logging(verbose: bool = False):
        """Setup logging configuration."""
        level = logging.DEBUG if verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(sys.stdout)
            ]
        )
    
    @staticmethod
    def create_parser() -> argparse.ArgumentParser:
        """Create and configure argument parser."""
        parser = argparse.ArgumentParser(
            description="Professional Log Parser - Extract specific commands from system logs",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  %(prog)s --log-dir /var/log --commands systemctl reboot shutdown
  %(prog)s --command-file commands.txt --output results.csv --workers 8
  %(prog)s --interactive
            """
        )
        
        parser.add_argument(
            '--log-dir', '-d',
            default=LogParserConfig.DEFAULT_LOG_DIR,
            help=f'Directory to scan for log files (default: {LogParserConfig.DEFAULT_LOG_DIR})'
        )
        
        parser.add_argument(
            '--commands', '-c',
            nargs='+',
            help='Commands to search for (space-separated)'
        )
        
        parser.add_argument(
            '--command-file', '-f',
            help='File containing commands to search for (one per line)'
        )
        
        parser.add_argument(
            '--output', '-o',
            help='Output CSV file (default: auto-generated with timestamp)'
        )
        
        parser.add_argument(
            '--workers', '-w',
            type=int,
            default=4,
            help='Number of worker threads for parallel processing (default: 4)'
        )
        
        parser.add_argument(
            '--verbose', '-v',
            action='store_true',
            help='Enable verbose logging'
        )
        
        parser.add_argument(
            '--interactive', '-i',
            action='store_true',
            help='Run in interactive mode'
        )
        
        return parser
    
    def interactive_mode(self) -> LogParserConfig:
        """Run interactive configuration mode."""
        print("=== Interactive Log Parser Configuration ===\n")
        
        # Get log directory
        log_dir = input(f"Enter log directory path (default: {LogParserConfig.DEFAULT_LOG_DIR}): ").strip()
        if not log_dir:
            log_dir = LogParserConfig.DEFAULT_LOG_DIR
        
        # Get commands
        commands = None
        command_file = input("Enter path to command file (press Enter to specify commands manually): ").strip()
        
        if command_file:
            try:
                commands = self.load_commands_from_file(command_file)
                print(f"Loaded {len(commands)} commands from file")
            except Exception as e:
                print(f"Error loading command file: {e}")
                print("Falling back to manual command entry")
        
        if not commands:
            cmd_input = input("Enter commands to search for (space-separated): ").strip()
            commands = cmd_input.split() if cmd_input else LogParserConfig.DEFAULT_COMMANDS
        
        # Get output file
        output_file = input("Enter output CSV filename (press Enter for auto-generated): ").strip()
        
        # Get worker count
        workers_input = input("Enter number of worker threads (default: 4): ").strip()
        workers = int(workers_input) if workers_input.isdigit() else 4
        
        return LogParserConfig(
            commands=commands,
            log_directory=log_dir,
            output_file=output_file or None,
            max_workers=workers
        )


def main():
    """Main entry point."""
    cli = CommandLineInterface()
    parser = cli.create_parser()
    args = parser.parse_args()
    
    # Setup logging
    cli.setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    try:
        # Create configuration
        if args.interactive:
            config = cli.interactive_mode()
        else:
            # Determine commands
            commands = None
            if args.command_file:
                commands = cli.load_commands_from_file(args.command_file)
            elif args.commands:
                commands = args.commands
            
            config = LogParserConfig(
                commands=commands,
                log_directory=args.log_dir,
                output_file=args.output,
                max_workers=args.workers
            )
        
        # Display configuration
        print(f"\nConfiguration:")
        print(f" Log Directory: {config.log_directory}")
        print(f" Commands: {', '.join(config.commands)}")
        print(f" Output File: {config.output_file}")
        print(f" Workers: {config.max_workers}\n")
        
        # Run parser
        start_time = time.time()
        parser_instance = LogParser(config)
        entries = parser_instance.parse_logs()
        parser_instance.save_results(entries)
        
        # Display summary
        duration = time.time() - start_time
        print(f"\n✅ Parsing completed successfully!")
        print(f"📊 Found {len(entries)} matching log entries")
        print(f"⏱️ Total duration: {duration:.2f} seconds")
        print(f"📁 Results saved to: {config.output_file}")
        
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
