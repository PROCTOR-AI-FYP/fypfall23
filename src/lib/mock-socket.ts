// ═══════════════════════════════════════════
// ProctorAI Mock Socket Emitter
// Simulates live detection events firing on a
// timer during Live Monitor, matching the real
// Socket.io contract.
// ═══════════════════════════════════════════

import { type DetectionEvent, BehaviorType } from './types';

type EventHandler = (event: DetectionEvent) => void;

const studentPool = [
  { id: 'usr-010', name: 'Ahmed Raza' },
  { id: 'usr-011', name: 'Zainab Malik' },
  { id: 'usr-013', name: 'Hira Nawaz' },
  { id: 'usr-014', name: 'Ali Hassan Shah' },
  { id: 'usr-016', name: 'Hamza Qureshi' },
  { id: 'usr-017', name: 'Sara Javed' },
  { id: 'usr-019', name: 'Amna Rehman' },
  { id: 'usr-020', name: 'Faizan Ahmad' },
  { id: 'usr-021', name: 'Rabia Khan' },
  { id: 'usr-022', name: 'Danyal Mirza' },
];

const behaviorPool: BehaviorType[] = [
  BehaviorType.GazeDeviation,
  BehaviorType.HeadPoseViolation,
  BehaviorType.LipMovement,
  BehaviorType.PhoneDetected,
  BehaviorType.UnauthorisedObject,
];

function randomBehaviors(): BehaviorType[] {
  const count = Math.random() > 0.7 ? 2 : 1;
  const shuffled = [...behaviorPool].sort(() => Math.random() - 0.5);
  return shuffled.slice(0, count);
}

function generateMockDetection(sessionId: string): DetectionEvent {
  const student = studentPool[Math.floor(Math.random() * studentPool.length)];
  const behaviors = randomBehaviors();
  const perSignal: Partial<Record<BehaviorType, number>> = {};
  behaviors.forEach(b => {
    perSignal[b] = 0.5 + Math.random() * 0.45; // 0.50–0.95
  });

  const values = Object.values(perSignal) as number[];
  const compositeScore = Math.min(0.99, values.reduce((a, b) => a + b, 0) / values.length + 0.05);

  return {
    id: `det-live-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    sessionId,
    seatNumber: Math.floor(Math.random() * 48) + 1,
    studentId: student.id,
    studentName: student.name,
    behaviourTypes: behaviors,
    perSignal,
    compositeScore: parseFloat(compositeScore.toFixed(2)),
    snapshotPath: `/snapshots/${sessionId}/live-${Date.now()}.jpg`,
    detectedAt: new Date().toISOString(),
    status: 'New',
  };
}

export class MockSocketEmitter {
  private handlers: Map<string, EventHandler[]> = new Map();
  private intervalId: ReturnType<typeof setInterval> | null = null;
  private sessionId: string;

  constructor(sessionId: string) {
    this.sessionId = sessionId;
  }

  on(event: string, handler: EventHandler): void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, []);
    }
    this.handlers.get(event)!.push(handler);
  }

  off(event: string, handler: EventHandler): void {
    const handlers = this.handlers.get(event);
    if (handlers) {
      this.handlers.set(event, handlers.filter(h => h !== handler));
    }
  }

  private emit(event: string, data: DetectionEvent): void {
    const handlers = this.handlers.get(event);
    if (handlers) {
      handlers.forEach(h => h(data));
    }
  }

  startSimulation(): void {
    if (this.intervalId) return;

    // Fire an event every 5–15 seconds
    const scheduleNext = () => {
      const delay = 5000 + Math.random() * 10000;
      this.intervalId = setTimeout(() => {
        const detection = generateMockDetection(this.sessionId);
        this.emit('detection', detection);
        scheduleNext();
      }, delay) as unknown as ReturnType<typeof setInterval>;
    };

    // Fire first event quickly
    setTimeout(() => {
      this.emit('detection', generateMockDetection(this.sessionId));
      scheduleNext();
    }, 2000);
  }

  stopSimulation(): void {
    if (this.intervalId) {
      clearTimeout(this.intervalId as unknown as number);
      this.intervalId = null;
    }
  }

  disconnect(): void {
    this.stopSimulation();
    this.handlers.clear();
  }
}
