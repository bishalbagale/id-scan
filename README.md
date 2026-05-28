# Motel ID Scanner

Local scanner bridge and Chromium extension for filling guest ID fields from PDF417 driver license barcodes.

## What It Does

- Runs a local Flask API at `http://localhost:5000/scan`.
- Uses NAPS2 to capture an ID scan from a configured scanner profile.
- Preprocesses the scan with grayscale conversion, contrast enhancement, median filtering, and multiple barcode crop regions.
- Decodes PDF417 data with `zxing-cpp`.
- Extracts common AAMVA fields and returns them as JSON.
- Provides a Manifest V3 browser extension that injects a scan button into supported PMS pages.

## Requirements

- Windows for scanner capture and executable use.
- NAPS2 installed at `C:\Program Files\NAPS2\naps2.console.exe`.
- A NAPS2 scanner profile named `nScanId`.
- Python 3.11 or newer for local development.

## Development

Create and activate a virtual environment:

```sh
python -m venv .venv
```

Install dependencies:

```sh
pip install -r requirements.txt
```

Start the local API:

```sh
python server.py
```

The `/scan` endpoint expects a `POST` request and returns either:

```json
{
  "status": "success",
  "data": {
    "firstName": "",
    "lastName": "",
    "address": "",
    "city": "",
    "state": "",
    "zip": "",
    "licenseNumber": ""
  },
  "decodeVariant": ""
}
```

or an error response with an `errorCode` and message.

## Browser Extension

Load `MotelScannerExtension/` as an unpacked extension in Chromium or Edge.

The extension is configured for:

```text
*://*.skytouchhos.com/pms/*
```

and calls:

```text
http://localhost:5000/scan
```

## Build Windows Executable

Install PyInstaller in your environment, then run:

```sh
pyinstaller --onefile server.py
```

The executable will be written to `dist/server.exe`.

## Debug Output

Debug output is off by default.

To enable debug output for the Python server:

```sh
MOTEL_SCANNER_DEBUG=1 python server.py
```

On Windows PowerShell:

```powershell
$env:MOTEL_SCANNER_DEBUG = "1"
python server.py
```

To enable debug output for the built executable:

```powershell
$env:MOTEL_SCANNER_DEBUG = "1"
.\server.exe
```

When debug mode is enabled and a decode or parse error occurs, the app writes diagnostic files under `Desktop\MotelScannerDebug\<timestamp>` when the Desktop folder exists. Otherwise it writes under the current user's home directory.

Close that terminal or unset the variable to return to default non-debug behavior:

```powershell
Remove-Item Env:\MOTEL_SCANNER_DEBUG
```
