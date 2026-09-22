import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Wifi, WifiOff, Wrench } from 'lucide-react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { FormField, Input, Select } from '@/components/ui/FormElements';
import * as api from '@/lib/api';
import type { Classroom } from '@/lib/types';

export function ClassroomManagement() {
  const navigate = useNavigate();
  const [classrooms, setClassrooms] = useState<Classroom[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Classroom | null>(null);
  const [form, setForm] = useState({ name: '', building: '', capacity: 30, cameraStatus: 'Online' as Classroom['cameraStatus'] });
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true); setError('');
    api.getClassrooms().then(r => { setClassrooms(r.data); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  };
  useEffect(() => { load(); }, []);

  const cameraIcon = (status: Classroom['cameraStatus']) => {
    if (status === 'Online') return <Wifi size={14} className="text-(--color-success)" />;
    if (status === 'Maintenance') return <Wrench size={14} className="text-(--color-warning)" />;
    return <WifiOff size={14} className="text-(--color-text-muted)" />;
  };

  const openCreate = () => { setEditing(null); setForm({ name: '', building: '', capacity: 30, cameraStatus: 'Online' }); setFormErrors({}); setModalOpen(true); };
  const openEdit = (c: Classroom) => { setEditing(c); setForm({ name: c.name, building: c.building, capacity: c.capacity, cameraStatus: c.cameraStatus }); setFormErrors({}); setModalOpen(true); };

  const validate = () => {
    const e: Record<string, string> = {};
    if (!form.name.trim()) e.name = 'Name is required';
    if (!form.building.trim()) e.building = 'Building is required';
    if (form.capacity < 1) e.capacity = 'Capacity must be at least 1';
    setFormErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    try {
      if (editing) { await api.updateClassroom(editing.id, form); }
      else { await api.createClassroom({ ...form, createdAt: '' } as Classroom); }
      setModalOpen(false); load();
    } catch { setFormErrors({ _: 'Failed to save' }); }
    setSaving(false);
  };

  const columns: Column<Classroom>[] = [
    { key: 'name', header: 'Room', sortable: true, render: (c) => <span className="font-medium">{c.name}</span> },
    { key: 'building', header: 'Building', sortable: true },
    { key: 'capacity', header: 'Capacity', sortable: true },
    { key: 'cameraStatus', header: 'Camera', render: (c) => (
      <span className="inline-flex items-center gap-1.5 text-body-sm">{cameraIcon(c.cameraStatus)} {c.cameraStatus}</span>
    )},
    { key: 'seatMap', header: 'Seat map', render: (c) => (
      c.seatMap ? (
        <button onClick={(e) => { e.stopPropagation(); navigate(`/admin/classrooms/${c.id}/seats`); }}
          className="text-label text-(--color-accent-primary) hover:underline cursor-pointer">
          {c.seatMap.length} seats mapped
        </button>
      ) : <span className="text-label text-(--color-text-muted)">Not configured</span>
    )},
    { key: 'actions', header: '', width: '80px', render: (c) => (
      <button onClick={(e) => { e.stopPropagation(); openEdit(c); }} className="px-2 py-1 text-label text-(--color-accent-primary) hover:bg-(--color-accent-primary-subtle) rounded-[4px] cursor-pointer">Edit</button>
    )},
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-display-lg text-(--color-text-primary)">Classroom Management</h1>
        <Button onClick={openCreate}><Plus size={16} /> Add classroom</Button>
      </div>
      <DataTable columns={columns} data={classrooms} loading={loading} error={error} onRetry={load} emptyMessage="No classrooms configured" searchable rowKey={c => c.id} />
      <Modal isOpen={modalOpen} onClose={() => setModalOpen(false)} title={editing ? 'Edit classroom' : 'Add classroom'}
        footer={<><Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button><Button onClick={handleSave} loading={saving}>{editing ? 'Save' : 'Create'}</Button></>}>
        <div className="flex flex-col gap-4">
          {formErrors._ && <p className="text-body-sm text-(--color-error)">{formErrors._}</p>}
          <FormField label="Room name" error={formErrors.name} required><Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} hasError={!!formErrors.name} placeholder="LH-4" /></FormField>
          <FormField label="Building" error={formErrors.building} required><Input value={form.building} onChange={e => setForm(f => ({ ...f, building: e.target.value }))} hasError={!!formErrors.building} placeholder="Block A" /></FormField>
          <FormField label="Capacity" error={formErrors.capacity} required><Input type="number" min={1} value={form.capacity} onChange={e => setForm(f => ({ ...f, capacity: parseInt(e.target.value) || 0 }))} hasError={!!formErrors.capacity} /></FormField>
          <FormField label="Camera status"><Select value={form.cameraStatus} onChange={e => setForm(f => ({ ...f, cameraStatus: e.target.value as Classroom['cameraStatus'] }))}><option value="Online">Online</option><option value="Offline">Offline</option><option value="Maintenance">Maintenance</option></Select></FormField>
        </div>
      </Modal>
    </div>
  );
}
