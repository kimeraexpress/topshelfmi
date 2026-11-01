import { list, put } from '@vercel/blob';
import fs from 'fs';
import path from 'path';

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate');
  res.setHeader('Pragma', 'no-cache');
  res.setHeader('Expires', '0');

  const fallbackPath = path.join(process.cwd(), 'data.json');
  const getFallbackData = () => {
    try {
      if (fs.existsSync(fallbackPath)) {
        return JSON.parse(fs.readFileSync(fallbackPath, 'utf8'));
      }
    } catch (e) {}
    return { categories: { ash: [], weed: [] }, products: [] };
  };

  // Se il token Blob non è configurato su Vercel, restituisce il data.json locale come fallback
  if (!process.env.BLOB_READ_WRITE_TOKEN) {
    if (req.method === 'GET') {
      return res.status(200).json(getFallbackData());
    } else {
      return res.status(500).json({
        error: 'BLOB_READ_WRITE_TOKEN non configurato su Vercel. Collega lo Storage Blob al progetto nel pannello Vercel.'
      });
    }
  }

  if (req.method === 'GET') {
    try {
      const { blobs } = await list({ prefix: 'data.json' });
      const blobItem = blobs.find(b => b.pathname === 'data.json');

      if (blobItem) {
        const remoteRes = await fetch(`${blobItem.url}?t=${Date.now()}`);
        if (remoteRes.ok) {
          const data = await remoteRes.json();
          return res.status(200).json(data);
        }
      }

      // Prima esecuzione su Blob: inizializzalo con il data.json predefinito
      const initialData = getFallbackData();
      await put('data.json', JSON.stringify(initialData, null, 2), {
        access: 'public',
        addRandomSuffix: false,
        allowOverwrite: true,
        contentType: 'application/json',
      });
      return res.status(200).json(initialData);
    } catch (err) {
      console.error('Errore lettura Vercel Blob:', err);
      return res.status(200).json(getFallbackData());
    }
  }

  if (req.method === 'POST' || req.method === 'PUT') {
    try {
      let data = req.body;
      if (typeof data === 'string') {
        try { data = JSON.parse(data); } catch (e) {}
      }

      if (!data || !data.categories || !Array.isArray(data.products)) {
        return res.status(400).json({ error: 'Struttura dati non valida' });
      }

      const jsonStr = JSON.stringify(data, null, 2);
      const blob = await put('data.json', jsonStr, {
        access: 'public',
        addRandomSuffix: false,
        allowOverwrite: true,
        contentType: 'application/json',
      });

      return res.status(200).json({ success: true, url: blob.url });
    } catch (err) {
      console.error('Errore scrittura Vercel Blob:', err);
      return res.status(500).json({ error: err.message });
    }
  }

  return res.status(405).json({ error: 'Metodo non consentito' });
}
