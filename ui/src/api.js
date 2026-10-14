// Thin fetch wrapper. Cookie session + X-Requested-With (CSRF guard on the API).
export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(method, path, body, { form = false } = {}) {
  const headers = { 'X-Requested-With': 'sav' };
  let payload;
  if (form) {
    payload = body;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload, credentials: 'same-origin' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(data.error || `HTTP ${res.status}`, res.status);
  return data;
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body ?? {}),
  put: (path, body) => request('PUT', path, body),
  patch: (path, body) => request('PATCH', path, body),
  del: (path) => request('DELETE', path),
  upload: (path, file) => {
    const fd = new FormData();
    fd.append('file', file);
    return request('POST', path, fd, { form: true });
  },
};

export const fileUrl = (projectId, name, bust) =>
  `/api/projects/${projectId}/files/${name}${bust ? `?v=${bust}` : ''}`;
