#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "boto3",
#     "python-dotenv",
#     "rich",
#     "psutil",
# ]
# ///

import os
import sys
import subprocess
import datetime
import argparse
import shutil
import tempfile
from pathlib import Path

import boto3
from botocore.config import Config
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn
from rich.prompt import Confirm, Prompt
import psutil

# --- Configuration & Defaults ---
CONSOLE = Console()
DEFAULT_OPENCLAW_PATH = Path.home() / ".openclaw"
DEFAULT_BACKUP_DIR = Path.home() / "backups" / "openclaw"

# Exclusion patterns for tar
EXCLUDE_POLICIES = [
    ".openclaw/logs/*",
    ".openclaw/trash/*",
    ".openclaw/tmp/*",
    ".openclaw/backups/*",
    ".openclaw/node_modules/*",
    "*.log",
    "*.tmp",
    "*.deleted.*",
    "*.reset.*",
    "*.checkpoint.*",
    "*.tar.zst",
    "*.tar.gz",
    "*.zip",
    "*.gpg",
    ".git/*",
]

class OpenClawBackup:
    def __init__(self, args):
        self.args = args
        load_dotenv(Path(__file__).parent / ".env")
        
        self.openclaw_path = Path(os.getenv("OPENCLAW_PATH", DEFAULT_OPENCLAW_PATH)).expanduser()
        self.backup_root = Path(os.getenv("BACKUP_DIR", DEFAULT_BACKUP_DIR)).expanduser()
        self.backup_root.mkdir(parents=True, exist_ok=True)
        
        self.timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.archive_name = f"openclaw-{self.timestamp}.tar.zst"
        self.temp_dir = Path(tempfile.mkdtemp(prefix="oc_backup_"))
        
        # R2 Config
        self.r2_endpoint = os.getenv("R2_ENDPOINT_URL")
        self.r2_key = os.getenv("R2_ACCESS_KEY_ID")
        self.r2_secret = os.getenv("R2_SECRET_ACCESS_KEY")
        self.r2_bucket = os.getenv("R2_BUCKET_NAME")
        self.r2_prefix = os.getenv("R2_PREFIX", "").strip("/") # Folder inside bucket
        
        # Encryption
        self.password = self.args.password or os.getenv("BACKUP_PASSWORD")

    def _get_system_info(self) -> str:
        info = [
            "# OpenClaw Backup Metadata",
            f"Date: {datetime.datetime.now().isoformat()}",
            f"Hostname: {os.uname().nodename}",
            f"OS: {os.uname().sysname} {os.uname().release}"
        ]
        
        try:
            res = subprocess.run(["openclaw", "--version"], capture_output=True, text=True)
            info.append(f"OpenClaw Version: {res.stdout.strip()}")
        except:
            info.append("OpenClaw Version: Unknown")

        try:
            res = subprocess.run(["node", "--version"], capture_output=True, text=True)
            info.append(f"Node.js Version: {res.stdout.strip()}")
        except:
            info.append("Node.js Version: Unknown")

        info.append("\n## Hardware Info")
        info.append(f"CPU: {psutil.cpu_count()} cores")
        info.append(f"RAM Total: {psutil.virtual_memory().total // (1024**2)} MB")
        
        return "\n".join(info)

    def _create_readme(self):
        readme_path = self.temp_dir / "BACKUP_README.md"
        with open(readme_path, "w") as f:
            f.write(self._get_system_info())
        return readme_path

    def _shorten_path(self, path: Path) -> str:
        try:
            return str(path).replace(str(Path.home()), "~")
        except:
            return str(path)

    def run(self):
        oc_display = self._shorten_path(self.openclaw_path)
        CONSOLE.print(Panel.fit(f"[bold blue]OpenClaw Backup System[/bold blue]", subtitle=f"Target: {oc_display}"))
        
        if not self.openclaw_path.exists():
            CONSOLE.print(f"[red]Error: OpenClaw directory not found at {oc_display}[/red]")
            sys.exit(1)

        readme_path = self._create_readme()
        final_archive_path = self.backup_root / self.archive_name
        display_archive_path = self._shorten_path(final_archive_path)
        
        # Build commands for piped execution: tar | zstd
        tar_cmd = ["tar"]
        for pattern in EXCLUDE_POLICIES:
            tar_cmd.extend(["--exclude", pattern])
        
        tar_cmd.extend(["-C", str(self.temp_dir), "BACKUP_README.md"])
        tar_cmd.extend(["-C", str(self.openclaw_path.parent), self.openclaw_path.name])
        tar_cmd.extend(["-cf", "-"])

        zstd_cmd = ["zstd", "-T0", "-19", "-o", str(final_archive_path)]

        try:
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
                progress.add_task(description="Compressing (tar | zstd -T0 -19)...", total=None)
                
                p_tar = subprocess.Popen(tar_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                p_zstd = subprocess.Popen(zstd_cmd, stdin=p_tar.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                p_tar.stdout.close()
                _, stderr_zstd = p_zstd.communicate()
                p_tar.wait()

                if p_zstd.returncode != 0:
                    raise Exception(f"Zstd error: {stderr_zstd.decode()}")
            
            CONSOLE.print(f"  [bold cyan]✓ 📦 Packaged:[/bold cyan] [grey50]{display_archive_path}[/grey50]")
        except Exception as e:
            CONSOLE.print(f"[red]Error during compression: {str(e)}[/red]")
            self.cleanup()
            sys.exit(1)

        # 3. Encryption (Optional)
        should_encrypt = False
        if not self.args.auto:
            if self.args.encrypt or Confirm.ask("Encrypt archive with password?", default=False):
                should_encrypt = True
                if not self.password:
                    self.password = Prompt.ask("[yellow]Enter backup password[/yellow]", password=True)
        else:
            if self.password or self.args.encrypt:
                should_encrypt = True

        if should_encrypt:
            if not self.password:
                CONSOLE.print("[red]Error: Encryption requested but no password provided.[/red]")
                self.cleanup()
                sys.exit(1)
                
            encrypted_path = final_archive_path.with_suffix(final_archive_path.suffix + ".gpg")
            display_encrypted_path = self._shorten_path(encrypted_path)
            gpg_cmd = ["gpg", "--batch", "--yes", "--symmetric", "--pinentry-mode", "loopback", "--passphrase-fd", "0", "--output", str(encrypted_path), str(final_archive_path)]
            
            try:
                with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
                    progress.add_task(description="Encrypting archive...", total=None)
                    subprocess.run(gpg_cmd, input=self.password.encode('utf-8'), check=True, capture_output=True)
                
                final_archive_path.unlink()
                final_archive_path = encrypted_path
                CONSOLE.print(f"  [bold cyan]✓ 🔒 Encrypted:[/bold cyan] [grey50]{display_encrypted_path}[/grey50]")
            except subprocess.CalledProcessError as e:
                CONSOLE.print(f"[red]Encryption failed: {e.stderr.decode()}[/red]")
                self.cleanup()
                sys.exit(1)

        # 4. R2 Upload
        should_upload = self.args.upload
        if not self.args.auto and not self.args.upload:
            should_upload = Confirm.ask("Upload to Cloudflare R2?", default=False)

        if should_upload:
            self.upload_to_r2(final_archive_path)

        self.cleanup()
        CONSOLE.print(f"\n[bold green]✓ Backup completed successfully![/bold green] 🦞✨")

    def upload_to_r2(self, file_path: Path):
        if not all([self.r2_endpoint, self.r2_key, self.r2_secret, self.r2_bucket]):
            CONSOLE.print("[yellow]Skipping R2 upload: missing credentials in .env[/yellow]")
            return

        try:
            s3 = boto3.client('s3', endpoint_url=self.r2_endpoint, aws_access_key_id=self.r2_key, aws_secret_access_key=self.r2_secret, config=Config(signature_version='s3v4'))
            file_size = file_path.stat().st_size
            
            # Construct object name with prefix (folder)
            object_name = file_path.name
            if self.r2_prefix:
                object_name = f"{self.r2_prefix}/{object_name}"

            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), DownloadColumn(), TransferSpeedColumn()) as progress:
                task = progress.add_task(f"Uploading to R2...", total=file_size)
                s3.upload_file(str(file_path), self.r2_bucket, object_name, Callback=lambda c: progress.update(task, advance=c))
            
            # Success message
            dest_display = f"{self.r2_bucket}/{self.r2_prefix}" if self.r2_prefix else self.r2_bucket
            CONSOLE.print(f"  [bold cyan]✓ 🌐 Uploaded:[/bold cyan] [grey50]{dest_display}[/grey50]")
        except Exception as e:
            # Prevent rich.markup errors by disabling highlighting for raw error messages
            CONSOLE.print(f"[red]R2 Upload failed: {str(e)}[/red]", highlight=False)

    def cleanup(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

def main():
    parser = argparse.ArgumentParser(description="OpenClaw Backup Tool")
    parser.add_argument("--auto", action="store_true", help="Non-interactive mode")
    parser.add_argument("--upload", action="store_true", help="Force upload to R2")
    parser.add_argument("--encrypt", action="store_true", help="Force encryption")
    parser.add_argument("--password", help="Password for encryption")
    
    args = parser.parse_args()
    try:
        backup = OpenClawBackup(args)
        backup.run()
    except KeyboardInterrupt:
        CONSOLE.print("\n[yellow]Backup cancelled by user.[/yellow]")
        sys.exit(0)
    except Exception as e:
        # Prevent rich.markup errors by disabling highlighting for raw error messages
        CONSOLE.print("[bold red]Critical Error:[/bold red]", highlight=False)
        CONSOLE.print(str(e), style="red", highlight=False)
        sys.exit(1)

if __name__ == "__main__":
    main()
