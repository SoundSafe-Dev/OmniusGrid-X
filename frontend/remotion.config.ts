/**
 * Remotion CLI config for the product demo video (video/src).
 *
 * Remotion bundles with webpack, not Vite, so the app's `import.meta.env`
 * reads must be materialized here. The whole object is defined at once —
 * `client.ts` uses `import.meta.env?.VITE_API_URL` (optional chaining),
 * which a per-key DefinePlugin replacement would not match.
 */
import { Config } from '@remotion/cli/config';
import { enableTailwind } from '@remotion/tailwind';
import webpack from 'webpack';

Config.overrideWebpackConfig((config) => {
  const withTailwind = enableTailwind(config);
  return {
    ...withTailwind,
    resolve: {
      ...withTailwind.resolve,
      alias: {
        ...(withTailwind.resolve?.alias ?? {}),
        // Mirror vite.config.ts — keeps any transitive plotly import resolvable
        'plotly.js/dist/plotly': 'plotly.js-dist-min',
        'plotly.js': 'plotly.js-dist-min',
      },
    },
    plugins: [
      ...(withTailwind.plugins ?? []),
      new webpack.DefinePlugin({
        // Specific member-chain defines MUST come alongside the whole-object
        // define: webpack's native import.meta handling constant-folds plain
        // `import.meta.env.X` member chains to undefined before the object
        // define applies; only optional-chain reads (`import.meta.env?.X`)
        // fall through to the object below.
        'import.meta.env.VITE_USE_MOCK': JSON.stringify('true'),
        'import.meta.env.VITE_MOCK_DELAY': JSON.stringify('0'),
        'import.meta.env.VITE_API_URL': JSON.stringify('http://127.0.0.1:1'),
        'import.meta.env.MODE': JSON.stringify('production'),
        'import.meta.env.DEV': 'false',
        'import.meta.env.PROD': 'true',
        'import.meta.env': JSON.stringify({
          BASE_URL: '/',
          MODE: 'production',
          DEV: false,
          PROD: true,
          SSR: false,
          // Turns on BOTH mock conventions (gated `=== 'true'` and default-on `!== 'false'`)
          VITE_USE_MOCK: 'true',
          // Zero the simulated network delay for deterministic frames
          VITE_MOCK_DELAY: '0',
          // Black-hole: anything unmocked fails fast instead of hanging the settle gate
          VITE_API_URL: 'http://127.0.0.1:1',
        }),
      }),
    ],
  };
});

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
