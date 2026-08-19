# Garment reference photos

Drop flat-lay photographs of real garments here, then run:

    python3 tools/import_garment_photos.py assets/garments/<file> --outfit <outfit_id>

A sheet holding several garments side by side can be split in one go:

    python3 tools/import_garment_photos.py assets/garments/sheet.jpg \
        --split 3 --outfits out_grand_agbada,out_modern_senator,out_classic_kaftan

## What makes a photo usable

The customer's fabric is painted onto the photograph while its own luminance —
folds, seams, contact shadows — is preserved. That only works when:

* **the garment is alone in frame.** No model. Masking a garment off a body is
  human parsing, which this app does not do; a face in shot is refused.
* **the background contrasts with the garment.** A cream shirt on a cream
  backdrop masks as *background*, and the fabric lands on the room instead.
  Dark garment on light ground, or light garment on dark ground.
* **the garment is plain.** Luminance cannot tell someone else's print from a
  fold, so a boldly patterned reference ghosts its old motif through the new
  cloth. Tonal embroidery is usually fine; a full wax print is not.

The importer checks all three and tells you which photos passed. Anything it
rejects is still stored on the outfit record, but composition falls back to the
vector template rather than producing a mess.
