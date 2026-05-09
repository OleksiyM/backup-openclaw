# OpenClaw Backup Tool 🛡️🦞

A Python utility for creating secure backups of your **OpenClaw** installation.

This tool provides a reliable backup solution that combines standard Unix tools with a modern CLI interface.

## Key Features ✨

*   **Zstd Compression:** Uses a `tar` + `zstd` pipeline with compression level `-19` and multi-threading (`-T0`) to minimize archive size.
*   **AES-256 Encryption:** Symmetric encryption via `gpg`. Your data remains private even in cloud storage.
*   **Cloudflare R2 Integration:** Automated upload to S3-compatible Cloudflare R2 storage with support for bucket prefixes (folders).
*   **Smart Exclusions:** Automatically skips logs, trash, temporary files, and `node_modules` to save space and time.
*   **Backup Metadata:** Every archive includes a `BACKUP_README.md` containing system info, hardware specs, and versions of OpenClaw/Node.js.
*   **Modern CLI Interface:** Powered by the `rich` library, featuring progress bars, color-coded stages, and spinners.
*   **Dual Operation Modes:** 
    *   **Interactive:** Guided experience with [y/N] confirmations.
    *   **Automated (`--auto`):** Ideal for `cron` jobs and CI/CD pipelines.

## Requirements 🛠️

*   [uv](https://github.com/astral-sh/uv) — Python project and tool manager.
*   `gpg` — for encryption.
*   `zstd` — for maximum compression.
*   `tar` — for archiving.

**macOS Installation:**
```bash
brew install zstd gnupg
```

**Ubuntu/Debian Installation:**
```bash
sudo apt update && sudo apt install zstd gnupg
```

## Getting Started 🚀

1. **Clone the project and configure environment:**
   ```bash
   cp .env.example .env
   nano .env
   ```
   *Fill in your R2 credentials. For encryption, it is highly recommended to use a password file (`--password-file`) or interactive prompt. You can also set `BACKUP_PASSWORD` in `.env` as a convenience option, but storing secrets in plaintext dotfiles is less secure.*

2. **Run the utility:**
   You can run it directly from the project directory:
   ```bash
   uv run openclaw-backup
   ```
   *Or install it globally to run from anywhere:*
   ```bash
   uv tool install .
   openclaw-backup
   ```

3. **Run automated backup with cloud upload:**
   ```bash
   uv run openclaw-backup --auto --upload
   ```

## Automation (Cron) ⏱️

To automatically run the backup every day at 2:00 AM, add this to your crontab (`crontab -e`):

```bash
# Run OpenClaw backup daily at 2:00 AM
0 2 * * * cd /path/to/backup-openclaw && /path/to/uv run openclaw-backup --auto --upload >> backup.log 2>&1
```
*(Make sure to replace `/path/to/` with your actual absolute paths. You can find `uv` path via `which uv`)*

## Command Line Options 💻

| Flag | Description |
| :--- | :--- |
| `--auto` | Disables interactive prompts (uses `.env` settings). |
| `--upload` | Forces upload to Cloudflare R2. |
| `--encrypt` | Forces GPG encryption. |
| `--password` | Allows passing the encryption password directly (not recommended). |
| `--password-file` | Path to a file containing the encryption password (recommended for automation). |

## Archive Structure 📦

Inside the encrypted `.tar.zst.gpg` file:
*   `BACKUP_README.md` — System metadata and backup "passport".
*   `.openclaw/` — Your full installation (agents, flows, identity, etc.).

## Manual Restoration 🔑

If your backup is in Cloudflare R2, first download the `.tar.zst.gpg` file using the AWS CLI, Cyberduck, or the Cloudflare dashboard.

To decrypt and extract the local backup archive in one command:
```bash
gpg -d backup_file.tar.zst.gpg | tar --zstd -xf -
```
