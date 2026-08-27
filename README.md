# Mimik to Zendesk

Converts Mimik browser workflow exports into cleaner Zendesk Help Center article HTML.

The converter removes Mimik-specific page formatting, extracts embedded screenshots, normalizes them to PNG, uploads them to Zendesk Guide Media, and writes an article-body fragment that already contains the Zendesk-hosted image paths.

The current workflow is:

```text
Mimik HTML export
    -> mimik_converter.py
    -> cleaned HTML + local screenshots
    -> screenshots uploaded to Zendesk Guide Media
    -> Zendesk /guide-media/... paths inserted into article-body.html
    -> converted package reviewed/edited in ChatGPT
    -> cleaned HTML pasted into the Zendesk article source editor
```

This end-to-end workflow has been tested successfully with a real Mimik guide and a Zendesk Help Center article.

## Requirements

- Windows
- Python 3
- A Zendesk OAuth client with Help Center write access
- Python dependencies from `requirements.txt`

Install the Python dependencies from PowerShell or Command Prompt:

```powershell
py -m pip install -r requirements.txt
```

If `py` is not available but `python` is:

```powershell
python -m pip install -r requirements.txt
```

## Zendesk OAuth setup

Authentication uses OAuth. Do not put Zendesk client secrets or access tokens in the repository.

Copy `.env.example` to `.env` and fill in the local values:

```env
ZENDESK_SUBDOMAIN=your-subdomain
ZENDESK_OAUTH_CLIENT_ID=mimik-to-zendesk
ZENDESK_OAUTH_CLIENT_SECRET=your-local-client-secret
ZENDESK_OAUTH_SCOPE=hc:write
```

`ZENDESK_SUBDOMAIN` should contain only the Zendesk subdomain, not a full URL.

For example, if the account is:

```text
https://example.zendesk.com/
```

use:

```env
ZENDESK_SUBDOMAIN=example
```

The `.env` file is ignored by Git and must remain local.

### Test authentication

`zendesk_auth.py` can be run independently to verify OAuth without displaying or saving the access token:

```powershell
py .\zendesk_auth.py
```

## Drag-and-drop use

Drag one or more Mimik `.html` files onto:

```text
Convert Mimik HTML.bat
```

Windows passes the dropped file paths to `mimik_converter.py`.

The converter displays progress while it:

1. Reads and parses the Mimik HTML.
2. Cleans the article and extracts screenshots.
3. Authenticates with Zendesk.
4. Uploads each screenshot to Zendesk Guide Media.
5. Writes the converted article package.

Each screenshot upload is reported individually so a long conversion does not appear to be stalled.

You can also run the converter directly:

```powershell
py .\mimik_converter.py "C:\Path\To\Article.html"
```

## What the converter changes

The converter currently:

- Removes the Mimik cover, header, footer, and print-oriented layout.
- Converts recognized Mimik headings to normal HTML headings.
- Flattens Mimik callout/note styling into normal article paragraphs while preserving the text.
- Preserves step order and step descriptions.
- Extracts Base64-embedded screenshots.
- Converts screenshots to PNG.
- Names step screenshots predictably, such as `step-01.png`.
- Keeps local screenshots for visual review.
- Uploads each screenshot to Zendesk Guide Media.
- Replaces local image paths in `article-body.html` with the `/guide-media/...` path returned by Zendesk.
- Leaves the original Mimik HTML unchanged.

## Output structure

The converter creates an article folder beside the script:

```text
Converted Mimik HTML\
    <Article Name>\
        article-body.html
        preview.html
        manifest.json
        media-manifest.json
        conversion-summary.txt
        images\
            step-01.png
            step-02.png
            ...
        source\
            original.html
```

### `article-body.html`

Zendesk-ready article-body HTML fragment.

Screenshot references use the Zendesk Guide Media paths returned by the API, for example:

```html
<img src="/guide-media/01EXAMPLE" alt="Example screenshot">
```

These relative `/guide-media/...` paths have been verified to load correctly when pasted into the Zendesk Help Center article source editor.

### `preview.html`

Standalone local preview of the converted article.

Unlike `article-body.html`, the preview continues to reference the PNG files in the local `images` folder. This keeps the package visually reviewable without depending on Zendesk.

### `images\`

Local copies of screenshots extracted from the Mimik export and normalized to PNG.

These are intentionally retained even after the images are uploaded to Zendesk. They are used for local review and for the ChatGPT editorial step.

### `media-manifest.json`

Maps each local screenshot to the Zendesk Guide Media object created for it.

The mapping includes:

- Local image filename
- Mimik step number
- Alt text
- Zendesk media ID
- Zendesk `/guide-media/...` path

### `manifest.json`

Machine-readable conversion information including:

- Article title
- Source filename
- Conversion time
- Extracted image metadata
- Screenshot count
- Zendesk media upload count
- Generated output files

### `conversion-summary.txt`

Human-readable summary of the conversion and generated package.

### `source\original.html`

A copy of the exact Mimik HTML export used for the conversion.

The source export itself is never modified.

## Zendesk Guide Media upload flow

`zendesk_media.py` implements Zendesk's three-stage Guide Media process:

1. Request a temporary upload URL from Zendesk.
2. Upload the PNG bytes to the provided storage URL using the returned headers.
3. Create the Guide Media object from the returned `asset_upload_id`.

The resulting Guide Media object provides the media ID and `/guide-media/...` URL used in the article HTML.

Authentication remains separate in `zendesk_auth.py`.

## Editorial workflow

The converter intentionally does not attempt to rewrite the article's wording beyond the structural Mimik cleanup.

The current editorial workflow is:

1. Convert the Mimik HTML.
2. Review the generated package, including the local screenshots.
3. Pass the package through the ChatGPT article editor for grammar, clarity, consistency, and screenshot/instruction review.
4. Preserve every Zendesk `/guide-media/...` image path during editing.
5. Paste the cleaned HTML into the Zendesk article source editor.
6. Review the rendered Zendesk article before publishing.

Keeping the local screenshots in the package allows the editorial step to visually verify that each instruction still corresponds to the correct screenshot while leaving the Zendesk-hosted image path untouched.

### ChatGPT editor instructions

The canonical ChatGPT Project instructions are stored in:

```text
CHATGPT_EDITOR_INSTRUCTIONS.txt
```

The file is plain text so its contents can be copied directly into the ChatGPT Project Instructions field without relying on Markdown formatting.

Keep this repository copy as the source of truth for the editorial prompt. If the ChatGPT Project instructions are changed, update `CHATGPT_EDITOR_INSTRUCTIONS.txt` as well so the instructions remain versioned with the converter.

A shared ChatGPT Project may also be used to distribute the configured editor to other technicians, but the repository copy should still be maintained so the workflow does not depend on one ChatGPT Project configuration.

## Re-running an article

If an output folder with the same article title already exists, the converter replaces the local converted folder with a fresh conversion.

The original Mimik export is not modified.

At present, rerunning a conversion also uploads fresh copies of every screenshot to Zendesk Guide Media. Duplicate detection is not implemented yet.

## Security

- Never commit `.env`.
- Never hardcode a Zendesk client secret or OAuth access token.
- OAuth access tokens are held only in memory.
- The authentication test does not print or save the access token.
- Temporary signed upload URLs should not be logged or stored.
- `.env.example` must contain placeholders only.

## Project status

The core workflow is operational and has been validated end-to-end:

```text
Mimik HTML
    -> local conversion
    -> screenshot extraction
    -> Zendesk OAuth authentication
    -> Zendesk Guide Media upload
    -> /guide-media/... references in article HTML
    -> ChatGPT editorial cleanup
    -> Zendesk Help Center article
```

## TODO

- [ ] Add persistent screenshot hash/media tracking so rerunning an article can reuse an existing Zendesk Guide Media object instead of uploading duplicate images. The tracking data must live outside the per-article output folder because that folder is replaced on each conversion.
- [ ] Automatically create a ZIP of the converted article package for the ChatGPT editorial workflow while still leaving the normal folder available locally.
- [ ] Test the complete Zendesk-enabled workflow with multiple Mimik HTML files dropped onto the BAT file at the same time.
- [ ] Decide how reruns should handle Zendesk Guide Media objects that are no longer referenced after a guide changes, without automatically deleting media that may already be used by a published article.
- [ ] Continue testing with additional Mimik guides to identify export-format edge cases before treating the converter as fully stable.
