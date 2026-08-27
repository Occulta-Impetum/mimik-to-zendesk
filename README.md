# Mimik HTML Converter

This package converts Mimik HTML exports into a cleaner local article package.

## First-time setup

Open Command Prompt or PowerShell in this folder and run:

```powershell
py -m pip install -r requirements.txt
```

If `py` is not available but `python` is:

```powershell
python -m pip install -r requirements.txt
```

## Drag-and-drop use

Drag one or more Mimik `.html` files onto:

`Convert Mimik HTML.bat`

Windows passes the dropped file paths to `mimik_converter.py`.

You can also run it directly:

```powershell
py .\mimik_converter.py "C:\Path\To\How to Use Device Detective in NinjaOne.html"
```

## Output structure

The converter creates this beside the script:

```text
Converted Mimik HTML\
    <Article Name>\
        preview.html
        article-body.html
        manifest.json
        conversion-summary.txt
        images\
            step-01.png
            step-02.png
            ...
        source\
            original.html
```

### preview.html
Standalone local preview with simple formatting and relative image references.

### article-body.html
Clean article-body HTML fragment intended to become the source for the future Zendesk uploader.

### images
Mimik's embedded screenshots extracted and normalized to PNG.

### manifest.json
Machine-readable details including the article title, source filename, image metadata, and converted filenames.

### source\original.html
A copy of the exact Mimik HTML used for that conversion.

## Re-running an article

If an output folder with the same article title already exists, the converter replaces that converted folder with a fresh conversion. It never modifies the original Mimik export.

## Current scope

This version intentionally does **not** connect to Zendesk yet. It performs only the local conversion step:

Mimik HTML -> clean HTML + PNG images + conversion package

The next stage can use `article-body.html`, `manifest.json`, and `images\` to upload images to the Zendesk Guide Media API and create a draft article.
