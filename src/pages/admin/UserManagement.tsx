import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { FormField, Input, Select } from '@/components/ui/FormElements';
import * as api from '@/lib/api';
import { type User, Role } from '@/lib/types';

// Mirrors the server-side rule: a 6-digit local part is always a Student
// self-service account; anything else is staff, provisioned only here by an
// Admin. Pure derived-state helper — no new dependency.
interface RoleConstraint {
  lockedRole?: Role;
  disabledRole?: Role;
  note?: string;
}

export function inferRoleConstraint(email: string): RoleConstraint {
  const localPart = (email.split('@')[0] || '').trim();
  if (!localPart) return {};
  if (/^\d{6}$/.test(localPart)) {
    return { lockedRole: Role.Student, note: '6-digit ID detected — role is fixed to Student' };
  }
  return { disabledRole: Role.Student, note: 'Staff email — choose the appropriate role' };
}

export function UserManagement() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [roleFilter, setRoleFilter] = useState<string>('');

  const [form, setForm] = useState({ name: '', email: '', role: Role.Student as Role, department: '', status: 'Active' as 'Active' | 'Inactive' });
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const loadUsers = () => {
    setLoading(true);
    setError('');
    const filters = roleFilter ? { role: roleFilter as Role } : undefined;
    api.getUsers(filters).then(res => { setUsers(res.data); setLoading(false); })
      .catch(e => { setError(e.message || 'Failed to load users'); setLoading(false); });
  };

  useEffect(() => { loadUsers(); }, [roleFilter]);

  // Guidance only applies while creating a new user — legacy fixture
  // accounts (e.g. name-based student emails) must remain editable without
  // this UX nudge trying to "correct" an already-provisioned role.
  const roleConstraint: RoleConstraint = editingUser ? {} : inferRoleConstraint(form.email);

  useEffect(() => {
    if (editingUser) return;
    const constraint = inferRoleConstraint(form.email);
    if (constraint.lockedRole && form.role !== constraint.lockedRole) {
      setForm(f => ({ ...f, role: constraint.lockedRole! }));
    } else if (constraint.disabledRole && form.role === constraint.disabledRole) {
      setForm(f => ({ ...f, role: Role.Teacher }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.email, editingUser]);

  const openCreate = () => {
    setEditingUser(null);
    setForm({ name: '', email: '', role: Role.Student, department: '', status: 'Active' });
    setFormErrors({});
    setModalOpen(true);
  };

  const openEdit = (user: User) => {
    setEditingUser(user);
    setForm({ name: user.name, email: user.email, role: user.role, department: user.department, status: user.status });
    setFormErrors({});
    setModalOpen(true);
  };

  const validate = () => {
    const e: Record<string, string> = {};
    if (!form.name.trim()) e.name = 'Name is required';
    if (!form.email.trim()) e.email = 'Email is required';
    else if (!form.email.includes('@')) e.email = 'Enter a valid email';
    if (!form.department.trim()) e.department = 'Department is required';
    setFormErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    try {
      if (editingUser) {
        await api.updateUser(editingUser.id, form);
      } else {
        await api.createUser(form);
      }
      setModalOpen(false);
      loadUsers();
    } catch {
      setFormErrors({ _: 'Failed to save user' });
    }
    setSaving(false);
  };

  const handleDelete = async (id: string) => {
    await api.deleteUser(id);
    setDeleteConfirm(null);
    loadUsers();
  };

  const columns: Column<User>[] = [
    { key: 'name', header: 'Name', sortable: true, render: (u) => (
      <span className="font-medium text-(--color-text-primary)">{u.name}</span>
    )},
    { key: 'email', header: 'Email', sortable: true },
    { key: 'role', header: 'Role', sortable: true, render: (u) => (
      <span className="px-2 py-0.5 rounded-[2px] bg-(--color-accent-primary-subtle) text-(--color-accent-primary) text-label font-medium">
        {u.role}
      </span>
    )},
    { key: 'department', header: 'Department', sortable: true },
    { key: 'status', header: 'Status', render: (u) => (
      <span className={`px-2 py-0.5 rounded-[2px] text-label font-medium ${u.status === 'Active' ? 'bg-(--color-success-subtle) text-(--color-success)' : 'bg-(--color-bg-surface-raised) text-(--color-text-muted)'}`}>
        {u.status}
      </span>
    )},
    { key: 'actions', header: '', width: '120px', render: (u) => (
      <div className="flex items-center gap-1">
        <button onClick={(e) => { e.stopPropagation(); openEdit(u); }} className="px-2 py-1 text-label text-(--color-accent-primary) hover:bg-(--color-accent-primary-subtle) rounded-[4px] transition-colors cursor-pointer">
          Edit
        </button>
        <button onClick={(e) => { e.stopPropagation(); setDeleteConfirm(u.id); }} className="px-2 py-1 text-label text-(--color-error) hover:bg-(--color-error-subtle) rounded-[4px] transition-colors cursor-pointer">
          Delete
        </button>
      </div>
    )},
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-display-lg text-(--color-text-primary)">User Management</h1>
        <Button onClick={openCreate} size="md">
          <Plus size={16} /> Add user
        </Button>
      </div>

      <DataTable
        columns={columns}
        data={users}
        loading={loading}
        error={error}
        onRetry={loadUsers}
        emptyMessage="No users found"
        searchable
        searchPlaceholder="Search users by name, email, or role..."
        rowKey={(u) => u.id}
        filters={
          <Select value={roleFilter} onChange={e => setRoleFilter(e.target.value)} className="w-40">
            <option value="">All roles</option>
            {Object.values(Role).map(r => <option key={r} value={r}>{r}</option>)}
          </Select>
        }
      />

      {/* Create/Edit Modal */}
      <Modal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editingUser ? 'Edit user' : 'Add new user'}
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleSave} loading={saving}>
              {editingUser ? 'Save changes' : 'Create user'}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          {formErrors._ && <p className="text-body-sm text-(--color-error)">{formErrors._}</p>}
          <FormField label="Full name" error={formErrors.name} required>
            <Input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} hasError={!!formErrors.name} placeholder="Dr. Jane Smith" />
          </FormField>
          <FormField label="Email" error={formErrors.email} required>
            <Input value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} hasError={!!formErrors.email} placeholder="jane.smith@au.edu.pk" type="email" />
          </FormField>
          <FormField label="Role" required>
            <Select
              value={form.role}
              onChange={e => setForm(f => ({ ...f, role: e.target.value as Role }))}
              disabled={!!roleConstraint.lockedRole}
            >
              {Object.values(Role).map(r => (
                <option
                  key={r}
                  value={r}
                  disabled={(roleConstraint.lockedRole && r !== roleConstraint.lockedRole) || roleConstraint.disabledRole === r}
                >
                  {r}
                </option>
              ))}
            </Select>
            {roleConstraint.note && (
              <p className="text-label text-(--color-text-muted) mt-1">{roleConstraint.note}</p>
            )}
          </FormField>
          <FormField label="Department" error={formErrors.department} required>
            <Input value={form.department} onChange={e => setForm(f => ({ ...f, department: e.target.value }))} hasError={!!formErrors.department} placeholder="Computer Science" />
          </FormField>
          <FormField label="Status">
            <Select value={form.status} onChange={e => setForm(f => ({ ...f, status: e.target.value as 'Active' | 'Inactive' }))}>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </Select>
          </FormField>
        </div>
      </Modal>

      {/* Delete Confirmation */}
      <Modal isOpen={!!deleteConfirm} onClose={() => setDeleteConfirm(null)} title="Confirm deletion" size="sm"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteConfirm(null)}>Cancel</Button>
            <Button variant="danger" onClick={() => deleteConfirm && handleDelete(deleteConfirm)}>Delete user</Button>
          </>
        }
      >
        <p className="text-body text-(--color-text-secondary)">
          This action cannot be undone. The user will lose access to ProctorAI immediately.
        </p>
      </Modal>
    </div>
  );
}
