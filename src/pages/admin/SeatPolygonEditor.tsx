import { useState, useRef, useCallback, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/Button';
import { Undo2, Trash2, Save, ArrowLeft } from 'lucide-react';
import * as api from '@/lib/api';
import type { SeatPolygon, Classroom } from '@/lib/types';

interface Point { x: number; y: number; }

export function SeatPolygonEditor() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [classroom, setClassroom] = useState<Classroom | null>(null);
  const [seats, setSeats] = useState<SeatPolygon[]>([]);
  const [currentPoints, setCurrentPoints] = useState<Point[]>([]);
  const [nextSeatNumber, setNextSeatNumber] = useState(1);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    api.getClassroom(id).then(res => {
      setClassroom(res.data);
      if (res.data.seatMap) {
        setSeats(res.data.seatMap);
        setNextSeatNumber(res.data.seatMap.length + 1);
      }
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [id]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Background grid
    ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--color-border-default').trim() || '#DADCE0';
    ctx.lineWidth = 0.5;
    for (let x = 0; x < w; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
    for (let y = 0; y < h; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }

    // Draw existing seats
    const accentColor = getComputedStyle(document.documentElement).getPropertyValue('--color-accent-primary').trim() || '#2B5EA7';
    seats.forEach(seat => {
      ctx.beginPath();
      seat.vertices.forEach((v, i) => {
        if (i === 0) ctx.moveTo(v.x, v.y);
        else ctx.lineTo(v.x, v.y);
      });
      ctx.closePath();
      ctx.fillStyle = accentColor + '20';
      ctx.fill();
      ctx.strokeStyle = accentColor;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Seat number label
      const cx = seat.vertices.reduce((s, v) => s + v.x, 0) / seat.vertices.length;
      const cy = seat.vertices.reduce((s, v) => s + v.y, 0) / seat.vertices.length;
      ctx.fillStyle = accentColor;
      ctx.font = '12px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(seat.seatNumber), cx, cy);
    });

    // Draw current polygon being drawn
    if (currentPoints.length > 0) {
      ctx.beginPath();
      currentPoints.forEach((p, i) => {
        if (i === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      });
      ctx.strokeStyle = '#DC2626';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Draw points
      currentPoints.forEach(p => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#DC2626';
        ctx.fill();
      });
    }
  }, [seats, currentPoints]);

  useEffect(() => { draw(); }, [draw]);

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.round((e.clientX - rect.left) * (canvas.width / rect.width));
    const y = Math.round((e.clientY - rect.top) * (canvas.height / rect.height));
    setCurrentPoints(prev => [...prev, { x, y }]);
  };

  const handleDoubleClick = () => {
    if (currentPoints.length >= 3) {
      setSeats(prev => [...prev, { seatNumber: nextSeatNumber, vertices: currentPoints }]);
      setNextSeatNumber(n => n + 1);
      setCurrentPoints([]);
    }
  };

  const undoLastPoint = () => setCurrentPoints(prev => prev.slice(0, -1));
  const clearCurrent = () => setCurrentPoints([]);
  const removeLastSeat = () => {
    setSeats(prev => prev.slice(0, -1));
    setNextSeatNumber(n => Math.max(1, n - 1));
  };

  const handleSave = async () => {
    if (!id) return;
    setSaving(true);
    await api.updateClassroom(id, { seatMap: seats });
    setSaving(false);
    navigate('/admin/classrooms');
  };

  if (loading) {
    return <div className="flex items-center justify-center py-16"><div className="h-8 w-8 border-2 border-(--color-accent-primary) border-t-transparent rounded-full animate-spin" /></div>;
  }

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate('/admin/classrooms')} className="p-2 rounded-[6px] text-(--color-text-muted) hover:bg-(--color-bg-surface-raised) cursor-pointer">
          <ArrowLeft size={18} />
        </button>
        <div>
          <h1 className="text-display-lg text-(--color-text-primary)">Seat Polygon Editor</h1>
          <p className="text-body-sm text-(--color-text-secondary)">
            {classroom?.name}, {classroom?.building} — Click to add vertices, double-click to complete a seat polygon
          </p>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2 mb-4">
        <Button variant="secondary" size="sm" onClick={undoLastPoint} disabled={currentPoints.length === 0}>
          <Undo2 size={14} /> Undo point
        </Button>
        <Button variant="secondary" size="sm" onClick={clearCurrent} disabled={currentPoints.length === 0}>
          Clear current
        </Button>
        <Button variant="secondary" size="sm" onClick={removeLastSeat} disabled={seats.length === 0}>
          <Trash2 size={14} /> Remove last seat
        </Button>
        <div className="flex-1" />
        <span className="text-label text-(--color-text-muted)">
          {seats.length} seats mapped | Next: Seat {nextSeatNumber}
        </span>
        <Button onClick={handleSave} loading={saving}>
          <Save size={14} /> Save map
        </Button>
      </div>

      {/* Canvas */}
      <div className="bg-(--color-bg-surface) rounded-[6px] border border-(--color-border-default) p-4 overflow-auto">
        <canvas
          ref={canvasRef}
          width={720}
          height={480}
          onClick={handleCanvasClick}
          onDoubleClick={handleDoubleClick}
          className="border border-(--color-border-default) rounded-[4px] cursor-crosshair w-full max-w-[720px]"
          style={{ imageRendering: 'auto' }}
        />
      </div>

      <p className="text-body-sm text-(--color-text-muted) mt-3">
        Click to place vertices for a seat polygon. Double-click to complete the polygon and move to the next seat. Each polygon needs at least 3 vertices.
      </p>
    </div>
  );
}
