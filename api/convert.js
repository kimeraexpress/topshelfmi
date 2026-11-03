import { list, put } from '@vercel/blob';
import { createWriteStream, existsSync, readFileSync, unlinkSync, statSync, chmodSync, copyFileSync } from 'fs';
import { pipeline } from 'stream/promises';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

// Vercel serverless configuration
export const config = { maxDuration: 300 };

// ── Utility: scarica file da URL in /tmp ──
async function downloadFile(url, destPath) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Download fallito: ${res.status} ${res.statusText}`);
  const dest = createWriteStream(destPath);
  await pipeline(res.body, dest);
}

// ── Utility: pulizia /tmp ──
function cleanupFiles(...paths) {
  for (const p of paths) {
    try { if (existsSync(p)) unlinkSync(p); } catch (_) {}
  }
}

// ── Utility: risolve path eseguibile FFmpeg compatibile con Vercel Lambda ──
async function getFFmpegPath() {
  let ffmpegPath = 'ffmpeg';
  try {
    const installer = await import('@ffmpeg-installer/ffmpeg');
    ffmpegPath = installer.path || installer.default?.path || 'ffmpeg';
  } catch (e) {
    console.warn('[convert] @ffmpeg-installer non trovato, uso system ffmpeg:', e.message);
  }

  // Su ambiente Linux Lambda, assicurati che il binario sia eseguibile (copia in /tmp se necessario)
  if (process.platform !== 'win32' && ffmpegPath !== 'ffmpeg' && existsSync(ffmpegPath)) {
    try {
      chmodSync(ffmpegPath, 0o755);
    } catch (err) {
      try {
        const tmpBinary = '/tmp/ffmpeg';
        if (!existsSync(tmpBinary)) {
          copyFileSync(ffmpegPath, tmpBinary);
          chmodSync(tmpBinary, 0o755);
        }
        ffmpegPath = tmpBinary;
      } catch (copyErr) {
        console.warn('[convert] Fallita copia ffmpeg in /tmp:', copyErr.message);
      }
    }
  }

  return ffmpegPath;
}

// ── Utility: run FFmpeg ──
async function runFFmpeg(args) {
  const ffmpegPath = await getFFmpegPath();
  const cmd = `"${ffmpegPath}" ${args}`;
  const { stdout, stderr } = await execAsync(cmd, { maxBuffer: 100 * 1024 * 1024 });
  return { stdout, stderr };
}

export default async function handler(req, res) {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  if (!process.env.BLOB_READ_WRITE_TOKEN) {
    return res.status(500).json({ error: 'BLOB_READ_WRITE_TOKEN non configurato su Vercel' });
  }

  let body = req.body;
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch (e) {}
  }

  const { videoUrl, productId, strain, category, subcategory, tag } = body || {};

  if (!videoUrl) {
    return res.status(400).json({ error: 'Parametro videoUrl mancante' });
  }

  const tmpId = productId || ('prod_' + Date.now());
  const safeId = tmpId.replace(/[^a-z0-9_]/gi, '_');
  const inputPath  = `/tmp/input_${safeId}.mov`;
  const outputPath = `/tmp/output_${safeId}.mp4`;
  const posterPath = `/tmp/poster_${safeId}.jpg`;

  try {
    // ── 1. Download video grezzo da Vercel Blob ──
    console.log(`[convert] Scaricamento video da ${videoUrl}...`);
    await downloadFile(videoUrl, inputPath);

    const inputSize = statSync(inputPath).size;
    console.log(`[convert] Input scaricato: ${(inputSize / 1024 / 1024).toFixed(1)} MB`);

    // ── 2. Converti in 1080p H.264 MP4 (FastStart, 8-bit YUV420P universale) ──
    // scale=-2:1920 assicura altezza 1080p verticale (1080x1920) e larghezza pari
    // pix_fmt yuv420p garantisce compatibilità totale anche da sorgenti iPhone HDR/10bit
    const ffmpegArgs = [
      '-y',
      `-i "${inputPath}"`,
      '-vcodec libx264',
      '-preset veryfast',
      '-b:v 6000k',
      '-maxrate 8000k',
      '-bufsize 12000k',
      '-profile:v high',
      '-pix_fmt yuv420p',
      '-vf "scale=-2:1920"',
      '-movflags +faststart',
      '-c:a aac',
      '-b:a 128k',
      `"${outputPath}"`
    ].join(' ');

    console.log('[convert] Avvio transcodifica 1080p FFmpeg...');
    await runFFmpeg(ffmpegArgs);

    const outputSize = statSync(outputPath).size;
    console.log(`[convert] Transcodifica completata! Output MP4: ${(outputSize / 1024 / 1024).toFixed(1)} MB`);

    // ── 3. Estrai frame poster a 0.6s per anteprima istantanea ──
    const posterArgs = [
      '-y',
      '-ss 00:00:00.600',
      `-i "${outputPath}"`,
      '-vframes 1',
      '-vf "scale=540:960"',
      '-q:v 3',
      `"${posterPath}"`
    ].join(' ');

    let posterUrl = null;
    try {
      console.log('[convert] Estrazione poster frame...');
      await runFFmpeg(posterArgs);
      if (existsSync(posterPath)) {
        const posterName = `images/posters/${safeId}.jpg`;
        const posterBuffer = readFileSync(posterPath);
        const posterBlob = await put(posterName, posterBuffer, {
          access: 'public',
          addRandomSuffix: false,
          allowOverwrite: true,
          contentType: 'image/jpeg',
        });
        posterUrl = posterBlob.url;
        console.log('[convert] Poster salvato su Blob:', posterUrl);
      }
    } catch (posterErr) {
      console.warn('[convert] Impossibile estrarre poster:', posterErr.message);
    }

    // ── 4. Upload MP4 ottimizzato su Vercel Blob ──
    const catFolder = (category || 'ash').toLowerCase();
    const subFolder = (subcategory || 'general').toLowerCase();
    const mp4Name = `videos/${catFolder}/${subFolder}/${safeId}_1080p.mp4`;
    const mp4Buffer = readFileSync(outputPath);
    const mp4Blob = await put(mp4Name, mp4Buffer, {
      access: 'public',
      addRandomSuffix: false,
      allowOverwrite: true,
      contentType: 'video/mp4',
    });
    console.log('[convert] Video 1080p caricato su Blob:', mp4Blob.url);

    // ── 5. Leggi catalogo attuale direttamente da Vercel Blob ──
    let catalog = { categories: { ash: [], weed: [] }, products: [] };
    try {
      const { blobs } = await list({ prefix: 'data.json' });
      const blobItem = blobs.find(b => b.pathname === 'data.json');
      if (blobItem) {
        const remoteRes = await fetch(`${blobItem.url}?t=${Date.now()}`);
        if (remoteRes.ok) {
          catalog = await remoteRes.json();
        }
      }
    } catch (catErr) {
      console.warn('[convert] Errore lettura data.json da Blob:', catErr.message);
    }

    if (!catalog.products || !Array.isArray(catalog.products)) {
      catalog.products = [];
    }
    if (!catalog.categories) {
      catalog.categories = { ash: [], weed: [] };
    }

    // ── 6. Aggiorna o inserisci prodotto nel catalogo ──
    const existingIdx = productId ? catalog.products.findIndex(p => p.id === productId) : -1;

    if (existingIdx !== -1) {
      catalog.products[existingIdx] = {
        ...catalog.products[existingIdx],
        category: category || catalog.products[existingIdx].category || 'ash',
        subcategory: subcategory || catalog.products[existingIdx].subcategory || 'static',
        strain: strain || catalog.products[existingIdx].strain,
        tag: tag || catalog.products[existingIdx].tag || (subcategory || 'static').toUpperCase(),
        video: mp4Blob.url,
        ...(posterUrl && { poster: posterUrl }),
      };
    } else {
      const newProd = {
        id: tmpId,
        category: category || 'ash',
        subcategory: subcategory || 'static',
        strain: strain || 'Nuovo Prodotto',
        tag: tag || (subcategory || 'static').toUpperCase(),
        video: mp4Blob.url,
        ...(posterUrl && { poster: posterUrl }),
      };
      catalog.products.unshift(newProd);
    }

    // ── 7. Salva catalogo aggiornato su Blob ──
    await put('data.json', JSON.stringify(catalog, null, 2), {
      access: 'public',
      addRandomSuffix: false,
      allowOverwrite: true,
      contentType: 'application/json',
    });
    console.log('[convert] Catalogo data.json salvato con successo!');

    return res.status(200).json({
      success: true,
      videoUrl: mp4Blob.url,
      posterUrl,
      productId: existingIdx !== -1 ? productId : tmpId,
      inputMB: (inputSize / 1024 / 1024).toFixed(1),
      outputMB: (outputSize / 1024 / 1024).toFixed(1),
    });

  } catch (err) {
    console.error('[convert] ERRORE durante conversione:', err);
    return res.status(500).json({ error: err.message || 'Errore durante la conversione del video' });

  } finally {
    // ── 8. Pulizia /tmp ──
    cleanupFiles(inputPath, outputPath, posterPath);
  }
}
