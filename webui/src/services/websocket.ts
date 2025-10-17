export type TaskEvent =
  | { event: 'snapshot'; task: unknown }
  | { event: 'status'; task_id: string; status: string; timestamp: string }
  | { event: 'log'; task_id: string; line: string }
  | { event: 'error'; task_id: string; message: string; timestamp: string };

type EventHandler = (event: TaskEvent) => void;

export class TaskWebSocket {
  private socket: WebSocket | null = null;
  private readonly baseUrl: string;
  private readonly handlers = new Set<EventHandler>();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private currentTaskId: string | null = null;

  constructor(baseUrl?: string) {
    if (baseUrl) {
      this.baseUrl = baseUrl.replace(/\/$/, '');
    } else if (typeof window !== 'undefined') {
      this.baseUrl = window.location.origin.replace(/\/$/, '');
    } else {
      this.baseUrl = 'http://127.0.0.1:8000';
    }
  }

  connect(taskId: string) {
    this.currentTaskId = taskId;
    const base = this.baseUrl.replace(/^http/, 'ws');
    const normalized = base.endsWith('/') ? base.slice(0, -1) : base;
    const url = `${normalized}/ws/tasks/${taskId}`;
    this.socket = new WebSocket(url);

    this.socket.onmessage = event => {
      try {
        const data = JSON.parse(event.data) as TaskEvent;
        this.handlers.forEach(handler => handler(data));
      } catch (error) {
        console.warn('Failed to parse websocket message', error);
      }
    };

    this.socket.onclose = () => {
      if (this.reconnectAttempts < this.maxReconnectAttempts && this.currentTaskId) {
        const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 10000);
        this.reconnectAttempts += 1;
        setTimeout(() => this.connect(this.currentTaskId!), delay);
      }
    };

    this.socket.onopen = () => {
      this.reconnectAttempts = 0;
    };
  }

  on(handler: EventHandler) {
    this.handlers.add(handler);
  }

  off(handler: EventHandler) {
    this.handlers.delete(handler);
  }

  close() {
    this.reconnectAttempts = this.maxReconnectAttempts;
    this.socket?.close();
    this.socket = null;
    this.handlers.clear();
  }
}
