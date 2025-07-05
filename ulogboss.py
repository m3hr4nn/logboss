#!/usr/bin/env python3
"""
Ultra-Fast Log Parser - Maximum Performance Optimized

Extreme performance-focused log parser with minimal overhead
and maximum throughput for processing large log files.
"""

import mmap
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path
from typing import List, Tuple, Set
import gzip
import bz2

# Pre-compiled patterns for maximum speed
DATE_PATTERN = re.compile(rb'\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}|\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\b')

class FastLogParser:
    """Ultra-fast log parser using memory mapping and multiprocessing."""
    
    __slots__ = ['command_pattern', 'commands_bytes', 'chunk_size', 'max_workers']
    
    def __init__(self, commands: List[str], chunk_size: int = 64*1024*1024):
        # Pre-compile everything for maximum speed
        self.commands_bytes = [cmd.encode('utf-8') for cmd in commands]
        pattern = b'\\b(?:' + b'|'.join(re.escape(cmd) for cmd in self.commands_bytes) + b')\\b'
        self.command_pattern = re.compile(pattern, re.IGNORECASE)
        self.chunk_size = chunk_size
        self.max_workers = cpu_count()
    
    def find_log_files(self, directory: str) -> List[Path]:
        """Ultra-fast file discovery using os.scandir."""
        files = []
        extensions = {b'.log', b'.gz', b'.bz2'}
        
        for entry in os.scandir(directory):
            if entry.is_file(follow_symlinks=False):
                name_bytes = entry.name.encode('utf-8')
                if any(name_bytes.endswith(ext) for ext in extensions):
                    files.append(Path(entry.path))
        
        return files
    
    def process_chunk(self, data: bytes, file_path: str, start_pos: int) -> List[Tuple[str, str, str, str]]:
        """Process a chunk of data with maximum efficiency."""
        results = []
        
        # Find all matches in one pass
        for match in self.command_pattern.finditer(data):
            # Find line boundaries efficiently
            line_start = data.rfind(b'\n', 0, match.start()) + 1
            line_end = data.find(b'\n', match.end())
            if line_end == -1:
                line_end = len(data)
            
            line = data[line_start:line_end]
            
            # Quick timestamp extraction
            timestamp = b''
            date_match = DATE_PATTERN.search(line)
            if date_match:
                timestamp = date_match.group(1)
            
            # Extract matched commands
            commands = set()
            for cmd_match in self.command_pattern.finditer(line):
                commands.add(cmd_match.group(0))
            
            try:
                results.append((
                    timestamp.decode('utf-8', errors='ignore'),
                    b'|'.join(commands).decode('utf-8', errors='ignore'),
                    file_path,
                    line.decode('utf-8', errors='ignore').strip()
                ))
            except:
                continue
        
        return results
    
    def process_file_mmap(self, file_path: Path) -> List[Tuple[str, str, str, str]]:
        """Process file using memory mapping for maximum speed."""
        try:
            # Handle different file types
            if file_path.suffix == '.gz':
                with gzip.open(file_path, 'rb') as f:
                    data = f.read()
            elif file_path.suffix == '.bz2':
                with bz2.open(file_path, 'rb') as f:
                    data = f.read()
            else:
                with open(file_path, 'rb') as f:
                    # Use mmap for large files
                    if f.seek(0, 2) > self.chunk_size:  # File size > chunk_size
                        f.seek(0)
                        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                            data = mm[:]
                    else:
                        f.seek(0)
                        data = f.read()
            
            return self.process_chunk(data, str(file_path), 0)
            
        except (OSError, IOError):
            return []
    
    def parse_parallel(self, log_files: List[Path]) -> List[Tuple[str, str, str, str]]:
        """Parse files in parallel using all available CPU cores."""
        all_results = []
        
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all files
            future_to_file = {
                executor.submit(self.process_file_mmap, file_path): file_path
                for file_path in log_files
            }
            
            # Collect results as fast as possible
            for future in as_completed(future_to_file):
                try:
                    results = future.result()
                    all_results.extend(results)
                except:
                    continue
        
        return all_results
    
    def save_fast(self, results: List[Tuple[str, str, str, str]], output_file: str):
        """Ultra-fast CSV writing using direct file operations."""
        with open(output_file, 'w', encoding='utf-8', newline='') as f:
            # Write header
            f.write('timestamp,command,file_path,log_line\n')
            
            # Write data with minimal formatting overhead
            for timestamp, command, file_path, log_line in results:
                # Quick CSV escaping
                log_line = log_line.replace('"', '""')
                f.write(f'{timestamp},{command},{file_path},"{log_line}"\n')


def main():
    """Optimized main function."""
    start_time = time.perf_counter()
    
    # Fast command loading
    commands = []
    if len(sys.argv) > 1:
        try:
            with open(sys.argv[1], 'r') as f:
                commands = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        except:
            pass
    
    if not commands:
        commands = ['systemctl', 'reboot', 'shutdown']
    
    # Fast directory input
    log_dir = sys.argv[2] if len(sys.argv) > 2 else '/var/log'
    
    # Initialize parser
    parser = FastLogParser(commands)
    
    # Find files
    print(f"Scanning {log_dir}...")
    log_files = parser.find_log_files(log_dir)
    print(f"Found {len(log_files)} files")
    
    if not log_files:
        print("No log files found")
        return
    
    # Process files
    print(f"Processing with {parser.max_workers} workers...")
    results = parser.parse_parallel(log_files)
    
    # Save results
    output_file = f"fast_results_{int(time.time())}.csv"
    parser.save_fast(results, output_file)
    
    # Performance stats
    duration = time.perf_counter() - start_time
    print(f"\n⚡ ULTRA-FAST RESULTS:")
    print(f"📊 Matches found: {len(results)}")
    print(f"⏱️  Total time: {duration:.3f} seconds")
    print(f"🚀 Processing rate: {len(log_files)/duration:.1f} files/sec")
    print(f"📁 Output: {output_file}")


if __name__ == "__main__":
    main()