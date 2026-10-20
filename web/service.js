/** Local job API. Preview is free; only a completed export requests a credit. */
export async function request(path, options = {}) {
  const response = await fetch(path, { credentials: 'same-origin', ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `서버 응답 오류 (${response.status})`);
  return data;
}

export async function readScore(file, { signal, key, time, onProgress = () => {} } = {}) {
  const headers = { 'Content-Type': file.type || 'application/octet-stream' };
  if (key) headers['X-Key-Hint'] = key;
  if (time) headers['X-Time-Signature'] = time;
  const job = await request('/api/jobs', { method: 'POST', headers, body: file, signal });
  const deadline = Date.now() + 5 * 60 * 1000;
  while (Date.now() < deadline) {
    const current = await request(`/api/jobs/${encodeURIComponent(job.id)}`, { signal });
    onProgress({ ...current, cached: job.cached });
    if (current.status === 'failed') throw new Error(current.error || '판독에 실패했습니다. 크레딧은 차감되지 않았습니다.');
    if (current.status === 'done') return { ...job, committed: !!current.charged, result: current.result };
    await new Promise((resolve, reject) => {
      const cancel = () => { clearTimeout(timer); reject(new DOMException('취소됨', 'AbortError')); };
      const timer = setTimeout(() => { signal?.removeEventListener('abort', cancel); resolve(); }, 900);
      if (signal?.aborted) cancel();
      else signal?.addEventListener('abort', cancel, { once: true });
    });
  }
  throw new Error('처리가 오래 걸립니다. 잠시 뒤 같은 파일로 다시 시도해 주세요. 크레딧은 차감되지 않았습니다.');
}

export function commitScore(id) {
  return request(`/api/jobs/${encodeURIComponent(id)}/commit`, { method: 'POST' });
}
