const SESSION_STORAGE_KEY = 'mineru-session-id';
const USER_STORAGE_KEY = 'mineru-user-id';
const USERNAME_STORAGE_KEY = 'mineru-username';

function generateId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function getSessionId(): string {
  if (typeof localStorage === 'undefined') {
    return 'anonymous';
  }
  let value = localStorage.getItem(SESSION_STORAGE_KEY);
  if (!value) {
    value = generateId();
    try {
      localStorage.setItem(SESSION_STORAGE_KEY, value);
    } catch (error) {
      console.warn('failed to persist session id', error);
    }
  }
  return value;
}

export function getUserId(): string | null {
  if (typeof localStorage === 'undefined') {
    return null;
  }
  return localStorage.getItem(USER_STORAGE_KEY);
}

export function setUserId(userId: string | null): void {
  if (typeof localStorage === 'undefined') {
    return;
  }
  if (userId) {
    localStorage.setItem(USER_STORAGE_KEY, userId);
  } else {
    localStorage.removeItem(USER_STORAGE_KEY);
  }
}

export function getUsername(): string | null {
  if (typeof localStorage === 'undefined') {
    return null;
  }
  return localStorage.getItem(USERNAME_STORAGE_KEY);
}

export function setUsername(username: string | null): void {
  if (typeof localStorage === 'undefined') {
    return;
  }
  if (username) {
    localStorage.setItem(USERNAME_STORAGE_KEY, username);
  } else {
    localStorage.removeItem(USERNAME_STORAGE_KEY);
  }
}
