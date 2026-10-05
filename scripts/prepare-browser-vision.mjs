import { copyFile, mkdir } from 'node:fs/promises';
import { rolldown } from 'rolldown';
import { fileURLToPath } from 'node:url';
const destination=new URL('../public/vision/wasm/',import.meta.url);
await mkdir(destination,{recursive:true});
for (const name of ['vision_wasm_internal.js','vision_wasm_internal.wasm','vision_wasm_nosimd_internal.js','vision_wasm_nosimd_internal.wasm']) {
  await copyFile(new URL(`../node_modules/@mediapipe/tasks-vision/wasm/${name}`,import.meta.url),new URL(name,destination));
}
// MediaPipe's WASM loader installs ModuleFactory with importScripts. A classic,
// fully bundled worker works in both Vite development and the hosted build.
const worker=await rolldown({input:fileURLToPath(new URL('../src/lib/vision/head.worker.ts',import.meta.url))});
try {
  await worker.write({file:fileURLToPath(new URL('../public/vision/head.worker.js',import.meta.url)),format:'iife',codeSplitting:false,minify:true});
} finally {await worker.close();}
