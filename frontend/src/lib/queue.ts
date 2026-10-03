/** Small concurrency-limited task queue so many visible widgets don't flood the API. */
export class TaskQueue {
  private running = 0;
  private pending: (() => Promise<void>)[] = [];

  constructor(private readonly concurrency: number) {}

  add(task: () => Promise<void>): void {
    this.pending.push(task);
    this.pump();
  }

  private pump(): void {
    while (this.running < this.concurrency && this.pending.length) {
      const task = this.pending.shift()!;
      this.running++;
      task().finally(() => {
        this.running--;
        this.pump();
      });
    }
  }
}
