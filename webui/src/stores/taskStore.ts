import { defineStore } from 'pinia';

export interface TaskSummary {
  task_id: string;
  status: string;
  backend: string;
  parse_method: string;
  created_at: string;
  updated_at: string;
  error?: string | null;
}

export interface TaskDetail extends TaskSummary {
  params: Record<string, unknown>;
  documents: Array<Record<string, unknown>>;
  logs: string[];
}

interface TaskState {
  tasks: TaskSummary[];
  currentTaskId: string | null;
  details: Record<string, TaskDetail>;
  isLoading: boolean;
  socketTaskId: string | null;
}

export const useTaskStore = defineStore('task', {
  state: (): TaskState => ({
    tasks: [],
    currentTaskId: null,
    details: {},
    isLoading: false,
    socketTaskId: null
  }),
  actions: {
    setTasks(list: TaskSummary[]) {
      this.tasks = list;
    },
    upsertTask(summary: TaskSummary) {
      const index = this.tasks.findIndex(t => t.task_id === summary.task_id);
      if (index >= 0) {
        this.tasks.splice(index, 1, summary);
      } else {
        this.tasks.unshift(summary);
      }
    },
    setCurrentTask(id: string | null) {
      this.currentTaskId = id;
    },
    setTaskDetail(task: TaskDetail) {
      this.details[task.task_id] = task;
      this.upsertTask(task);
    },
    appendLog(taskId: string, line: string) {
      const detail = this.details[taskId];
      if (detail) {
        detail.logs.push(line);
      }
    },
    setSocketTask(taskId: string | null) {
      this.socketTaskId = taskId;
    }
  }
});
