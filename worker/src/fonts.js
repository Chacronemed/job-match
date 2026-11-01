// The embedded font for the PDFs (Inter, SIL OFL 1.1, worker/fonts/). wrangler bundles the
// .ttf files as Data modules (wrangler.jsonc `rules`); Node cannot import them, so index.js
// loads this module lazily and the tests pass the bytes read from disk instead.
import bold from "../fonts/Inter-Bold.ttf";
import regular from "../fonts/Inter-Regular.ttf";

export const FONTS = { regular, bold };
