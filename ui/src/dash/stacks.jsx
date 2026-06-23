// hal0 dashboard — Stacks view (PR-5; spec §9).
//
// A Stack is a named, portable bundle of slots + their profiles + model
// assignments + capability selections — the runtime successor to the first-run
// Bundles picker. This view mirrors the Profiles page family: a header +
// summary strip, seed/custom card grids, a slide-in editor drawer, and a
// styled delete confirm. Stacks add three things Profiles don't:
//
//   • Apply — declarative load: a dry-run diff modal (before→after per slot)
//     that, on confirm, commits the slot config and converges the runtime.
//   • Active + drift — the applied stack wears an Active ribbon; a drift badge
//     flags when live config has been hand-edited since apply.
//   • Export / Import — a portable .hal0stack.json round-trip with a resolve
//     report (present / pullable / unresolvable) for missing models.
//
// Data: GET /api/stacks (useStacks). Reuses the .pf-* card/drawer/confirm
// styling from Profiles plus a small .st-* layer (overhaul stacks block in
// dashboard.css) for the active ribbon, drift badge, slot rows, and resolve
// report. Seeds are immutable: Edit becomes "Edit a copy"; Delete is disabled.

import { useState, useEffect } from 'react'
import {
  useStacks,
  useStackCreate,
  useStackUpdate,
  useStackDelete,
  useStackApply,
  useStackExport,
  useStackImport,
  useStackSnapshot,
} from '@/api/hooks/useStacks'
import { useModels } from '@/api/hooks/useModels'
import { useProfiles } from '@/api/hooks/useProfiles'

// Device hue, mirroring the Profiles backend palette (#751 tokens).
const DEVICE_META = {
  'gpu-rocm':   { label: 'ROCm',   color: 'var(--dev-rocm)' },
  'gpu-vulkan': { label: 'Vulkan', color: 'var(--dev-vulkan)' },
  npu:          { label: 'NPU',    color: 'var(--dev-npu)' },
  cpu:          { label: 'CPU',    color: 'var(--dev-cpu)' },
};
const DEVICES = Object.keys(DEVICE_META);

// Mirrors the API slug regex ^[a-z0-9][a-z0-9_-]{0,31}$.
const NAME_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;

const BLANK_SLOT = { slot: '', model: '', device: 'gpu-rocm', profile: '', mtp: false, capabilities: [] };
const BLANK = { name: '', description: '', icon: '', tags: '', slots: [{ ...BLANK_SLOT }] };

function toast(msg, kind = 'info') {
  if (typeof window !== 'undefined' && window.__hal0Toast) window.__hal0Toast(msg, kind);
}

function dev(name) { return DEVICE_META[name] || DEVICE_META.cpu; }

// ── slot chip ───────────────────────────────────────────────────────────────

function SlotChip({ entry }) {
  const meta = dev(entry.device || 'cpu');
  return (
    <span className="st-slotchip" style={{ '--bk': meta.color }}>
      <span className="pf-chip-dot" />
      <span className="mono st-slotchip-name">{entry.slot}</span>
      {entry.model && <span className="mono st-slotchip-model">{entry.model}</span>}
    </span>
  );
}

// ── Stack card ──────────────────────────────────────────────────────────────

function StackCard({ s, index, onApply, onEdit, onClone, onExport, onDelete }) {
  const isSeed = !!s.seed;
  const slots = s.slots || [];
  const accent = (slots[0] && DEVICE_META[slots[0].device]?.color) || 'var(--accent)';

  return (
    <div className={'pf-card st-card' + (s.active ? ' st-active' : '')}
      style={{ '--bk': accent, animationDelay: (index * 34) + 'ms' }}>
      <span className="pf-accent" />
      {s.active && (
        <span className={'st-ribbon' + (s.drift === 'modified' ? ' drift' : '')}>
          {s.drift === 'modified' ? 'Active · modified' : 'Active'}
        </span>
      )}
      <div className="pf-card-top">
        <div className="pf-headline">
          <div className="pf-intent">{s.icon ? s.icon + ' ' : ''}{s.name || s.slug}</div>
          <div className="pf-slug-row mono">
            <span className="pf-slug">{s.slug}</span>
          </div>
        </div>
        <div className="pf-metric">
          <span className="pf-tps num">{slots.length}</span>
          <span className="pf-tps-u mono">slot{slots.length === 1 ? '' : 's'}</span>
        </div>
      </div>

      {s.description && <div className="st-desc">{s.description}</div>}

      <div className="st-slots">
        {slots.length
          ? slots.map(e => <SlotChip key={e.slot} entry={e} />)
          : <span className="pf-unused mono">no slots</span>}
      </div>

      <div className="pf-chips">
        {(s.tags || []).map(t => <span className="pf-chip" key={t}>{t}</span>)}
        <span className="pf-grow" />
        {isSeed
          ? <span className="pf-chip seed immutable" title="Seed stacks are read-only">{Icons.lock} seed</span>
          : <span className="pf-chip custom">custom</span>}
      </div>

      <div className="pf-foot">
        <div className="pf-actions" style={{ width: '100%' }}>
          <button className="pf-btn primary" onClick={() => onApply(s)}
            title="Preview the diff, then load this stack" data-testid={`st-btn-apply-${s.slug}`}>
            {Icons.start} Apply
          </button>
          <button className="pf-btn" onClick={() => onExport(s)} title="Export .hal0stack.json"
            data-testid={`st-btn-export-${s.slug}`}>{Icons.download}</button>
          {isSeed ? (
            <button className="pf-btn" onClick={() => onClone(s)} title="Seeds are immutable — fork a copy"
              data-testid={`st-btn-editcopy-${s.slug}`}>{Icons.copy} Edit a copy</button>
          ) : (
            <>
              <button className="pf-btn" onClick={() => onClone(s)} title="Clone"
                data-testid={`st-btn-clone-${s.slug}`}>{Icons.copy}</button>
              <button className="pf-btn" onClick={() => onEdit(s)} title="Edit"
                data-testid={`st-btn-edit-${s.slug}`}>{Icons.edit} Edit</button>
            </>
          )}
          <span className="pf-grow" />
          <button className="pf-btn danger" onClick={() => onDelete(s)} disabled={isSeed}
            title={isSeed ? 'Seed stacks cannot be deleted' : 'Delete'}
            data-testid={`st-btn-delete-${s.slug}`}>{Icons.trash}</button>
        </div>
      </div>
    </div>
  );
}

// ── Section ─────────────────────────────────────────────────────────────────

function Section({ title, count, hint, children }) {
  return (
    <div className="pf-section">
      <div className="sec">
        <h2>{title}<span className="ct num">{count}</span></h2>
        {hint && <span className="pf-sec-hint mono">{hint}</span>}
        <span className="rule" />
      </div>
      <div className="pf-grid">{children}</div>
    </div>
  );
}

// ── Apply modal (dry-run diff → commit) ─────────────────────────────────────

function ApplyModal({ stack, onClose }) {
  const apply = useStackApply();
  const [phase, setPhase] = useState('loading');   // loading | preview | applying | done
  const [diff, setDiff] = useState(null);
  const [report, setReport] = useState(null);

  useEffect(() => {
    let alive = true;
    apply.mutateAsync({ slug: stack.slug, dryRun: true })
      .then(r => { if (alive) { setDiff(r); setPhase('preview'); } })
      .catch(err => { if (alive) { toast(err?.message || 'Preview failed', 'err'); onClose(); } });
    return () => { alive = false; };
    /* eslint-disable-next-line */
  }, [stack.slug]);

  async function commit() {
    setPhase('applying');
    try {
      const r = await apply.mutateAsync({ slug: stack.slug, dryRun: false });
      setReport(r.converged || null);
      setPhase('done');
      const errs = r.converged?.errors?.length || 0;
      toast(errs ? `Applied ${stack.slug} with ${errs} slot error(s)` : `Applied ${stack.slug}`,
        errs ? 'warn' : 'ok');
    } catch (err) {
      toast(err?.message || 'Apply failed', 'err');
      setPhase('preview');
    }
  }

  const changes = (diff?.changes || []).filter(c => c.changed);

  return (
    <div className="pf-scrim center" onMouseDown={onClose}>
      <div className="pf-confirm st-apply" onMouseDown={e => e.stopPropagation()} role="dialog"
        aria-label={`Apply ${stack.slug}`} aria-busy={phase === 'applying'}>
        <div className="pf-confirm-h pf-confirm-title mono">{Icons.start} Apply · {stack.name || stack.slug}</div>

        {phase === 'loading' && <div className="pf-confirm-b"><div className="empty mono">Computing diff…</div></div>}

        {(phase === 'preview' || phase === 'applying') && (
          <div className="pf-confirm-b">
            {changes.length ? (
              <>
                <div className="st-apply-sub mono">{changes.length} slot{changes.length > 1 ? 's' : ''} will change · un-named slots are unloaded</div>
                <div className="st-diff">
                  {changes.map(c => (
                    <div className="st-diff-row" key={c.slot}>
                      <span className="mono st-diff-slot">{c.slot}</span>
                      <span className="mono st-diff-from">{c.before_model || '∅'}</span>
                      <span className="st-diff-arrow">→</span>
                      <span className="mono st-diff-to">{c.after_model || '∅'}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="pf-confirm-sub">No slot changes — applying records this as the active stack and converges the runtime.</div>
            )}
          </div>
        )}

        {phase === 'done' && (
          <div className="pf-confirm-b">
            <div className="st-apply-sub mono ok">Applied.</div>
            {report && (
              <div className="st-report">
                {report.loaded.length > 0 && <div className="mono">loaded · {report.loaded.join(', ')}</div>}
                {report.swapped.length > 0 && <div className="mono">swapped · {report.swapped.join(', ')}</div>}
                {report.unloaded.length > 0 && <div className="mono">unloaded · {report.unloaded.join(', ')}</div>}
                {report.capabilities_applied.length > 0 && <div className="mono">capabilities · {report.capabilities_applied.join(', ')}</div>}
                {report.errors.length > 0 && (
                  <div className="mono" style={{ color: 'var(--err)' }}>
                    errors · {report.errors.map(e => `${e.target}: ${e.error}`).join('; ')}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        <div className="pf-confirm-foot">
          <button className="pf-btn" onClick={onClose} disabled={phase === 'applying'}>
            {phase === 'done' ? 'Close' : 'Cancel'}
          </button>
          {phase !== 'done' && (
            <button className="pf-btn primary solid" onClick={commit}
              disabled={phase !== 'preview'} data-testid="st-btn-apply-confirm">
              {phase === 'applying' ? 'Applying…' : 'Apply stack'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Import modal (file → dry-run resolve → commit) ──────────────────────────

function ImportModal({ existing, onClose, onImported }) {
  const imp = useStackImport();
  const [envelope, setEnvelope] = useState(null);
  const [report, setReport] = useState(null);
  const [slug, setSlug] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  async function onFile(file) {
    setErr('');
    try {
      const text = await file.text();
      const env = JSON.parse(text);
      setEnvelope(env);
      const r = await imp.mutateAsync({ envelope: env, dry_run: true });
      setReport(r);
      // Suggest a slug from the file name, kebab-cased.
      const base = (file.name || '').replace(/\.hal0stack\.json$|\.json$/i, '')
        .toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 32);
      setSlug(base || 'imported-stack');
    } catch (e) {
      setErr(e?.message || 'Not a valid .hal0stack.json envelope');
      setEnvelope(null); setReport(null);
    }
  }

  const slugTaken = existing.includes(slug);
  const slugValid = NAME_RE.test(slug) && !slugTaken;

  async function commit() {
    if (!slugValid) return;
    setBusy(true);
    try {
      await imp.mutateAsync({ envelope, slug });
      toast(`Imported as ${slug}`, 'ok');
      onImported();
    } catch (e) {
      toast(e?.message || 'Import failed', 'err');
    } finally { setBusy(false); }
  }

  return (
    <div className="pf-scrim center" onMouseDown={() => { if (!busy) onClose(); }}>
      <div className="pf-confirm st-apply" onMouseDown={e => e.stopPropagation()} role="dialog" aria-label="Import stack">
        <div className="pf-confirm-h pf-confirm-title mono">{Icons.download} Import stack</div>
        <div className="pf-confirm-b">
          {!report ? (
            <label className="st-drop">
              <input type="file" accept=".json,application/json" style={{ display: 'none' }}
                onChange={e => e.target.files?.[0] && onFile(e.target.files[0])}
                data-testid="st-import-file" />
              <span className="st-drop-glyph">{Icons.download}</span>
              <span className="mono">Choose a .hal0stack.json file</span>
              {err && <span className="pf-msg err mono hint err">{Icons.alert}{err}</span>}
            </label>
          ) : (
            <>
              <div className="st-apply-sub mono">
                {report.name || 'stack'} · schema v{report.schema_version} · checksum {report.checksum_ok ? 'ok' : '⚠ mismatch'}
              </div>
              <div className="st-resolve">
                {(report.resolutions || []).map(r => (
                  <div className={'st-resolve-row ' + r.status} key={r.model_id}>
                    <span className="mono st-resolve-id">{r.model_id}</span>
                    <span className={'pf-chip st-resolve-st ' + r.status}>{r.status}</span>
                    {r.status === 'pullable' && (
                      <button className="pf-btn" type="button"
                        onClick={() => { window.location.hash = '#models'; }}
                        title="Pull this model on the Models page">{Icons.download} Pull</button>
                    )}
                  </div>
                ))}
                {(!report.resolutions || report.resolutions.length === 0) && (
                  <div className="pf-unused mono">no model references</div>
                )}
              </div>
              {report.unresolvable?.length > 0 && (
                <div className="pf-msg warn mono">{Icons.alert}{report.unresolvable.length} model(s) unresolvable — those slots import disabled.</div>
              )}
              <label className="st-slugrow">
                <span className="pf-row-lbl">Save as</span>
                <input className={'pf-input mono' + (slug && !slugValid ? ' err' : '')} value={slug}
                  onChange={e => setSlug(e.target.value)} maxLength={32} placeholder="my-stack"
                  data-testid="st-import-slug" />
              </label>
              {slugTaken && <span className="pf-msg err mono hint err">{Icons.alert}“{slug}” already exists</span>}
            </>
          )}
        </div>
        <div className="pf-confirm-foot">
          <button className="pf-btn" onClick={onClose} disabled={busy}>Cancel</button>
          {report && (
            <button className="pf-btn primary solid" onClick={commit} disabled={!slugValid || busy}
              data-testid="st-import-confirm">{busy ? 'Importing…' : 'Import'}</button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Editor drawer (create / edit / clone) ───────────────────────────────────

function fromStack(s) {
  return {
    name: s.name || '',
    description: s.description || '',
    icon: s.icon || '',
    tags: (s.tags || []).join(', '),
    slots: (s.slots || []).map(e => ({
      slot: e.slot || '',
      model: e.model || '',
      device: e.device || 'gpu-rocm',
      profile: e.profile || '',
      mtp: !!e.mtp,
      capabilities: e.capabilities || [],
    })),
  };
}

function Drawer({ mode, source, existing = [], onClose, onSaved }) {
  const isEdit = mode === 'edit';
  const models = useModels().data || [];
  const profiles = useProfiles().data || [];

  const initial = (() => {
    if (mode === 'create') return source ? fromStack(source) : { ...BLANK, slots: [{ ...BLANK_SLOT }] };
    const base = fromStack(source);
    if (mode === 'clone') {
      const suffix = source.seed ? '-custom' : '-copy';
      return { ...base, _slug: (source.slug + suffix).slice(0, 32) };
    }
    return { ...base, _slug: source.slug };
  })();

  const [form, setForm] = useState(initial);
  const [slug, setSlug] = useState(initial._slug || '');
  const [submitting, setSubmitting] = useState(false);
  const [closing, setClosing] = useState(false);

  const create = useStackCreate();
  const update = useStackUpdate();

  useEffect(() => { setForm(initial); setSlug(initial._slug || ''); /* eslint-disable-next-line */ }, [mode, source]);

  const taken = existing.filter(n => !(isEdit && n === source?.slug));
  const slugErr = !slug.trim() ? 'Slug is required'
    : !NAME_RE.test(slug) ? 'lowercase · digits · - · _ · ≤32'
    : taken.includes(slug) ? `“${slug}” already exists` : '';
  const slotErr = !form.slots.length ? 'add at least one slot'
    : form.slots.some(s => !s.slot.trim()) ? 'every slot needs a name' : '';
  const blocking = (!isEdit && !!slugErr) || !!slotErr;

  const setSlot = (i, k, v) => setForm(f => ({
    ...f, slots: f.slots.map((s, j) => j === i ? { ...s, [k]: v } : s),
  }));
  const addSlot = () => setForm(f => ({ ...f, slots: [...f.slots, { ...BLANK_SLOT }] }));
  const rmSlot = (i) => setForm(f => ({ ...f, slots: f.slots.filter((_, j) => j !== i) }));
  const close = () => { if (submitting) return; setClosing(true); setTimeout(onClose, 200); };

  async function submit(e) {
    e.preventDefault();
    if (blocking) { toast('Fix the highlighted fields', 'warn'); return; }
    setSubmitting(true);
    const body = {
      name: form.name.trim(),
      description: form.description.trim(),
      icon: form.icon.trim(),
      tags: form.tags.split(',').map(t => t.trim()).filter(Boolean),
      slots: form.slots.map(s => ({
        slot: s.slot.trim(),
        model: s.model || null,
        device: s.device || null,
        profile: s.profile || null,
        mtp: s.mtp,
        capabilities: s.capabilities || [],
      })),
    };
    try {
      if (isEdit) {
        await update.mutateAsync({ slug: source.slug, stack: body });
        toast(`Stack ${source.slug} updated`, 'ok');
      } else {
        await create.mutateAsync({ slug: slug.trim(), stack: body });
        toast(`Stack ${slug.trim()} created`, 'ok');
      }
      onSaved();
    } catch (err) {
      const code = err?.code || '';
      if (code === 'stacks.exists') toast(`A stack named ${slug} already exists`, 'err');
      else if (code === 'stacks.seed_immutable') toast('Seed stacks cannot be modified', 'err');
      else toast(err?.message || 'Save failed', 'err');
    } finally { setSubmitting(false); }
  }

  const title = isEdit ? `Edit · ${source.slug}`
    : mode === 'clone' ? (source.seed ? `Edit a copy · ${source.slug}` : `Clone · ${source.slug}`)
    : 'New stack';
  const eyebrow = isEdit ? 'EDIT' : mode === 'clone' ? (source?.seed ? 'EDIT A COPY' : 'CLONE') : 'CREATE';

  return (
    <div className={'pf-scrim' + (closing ? ' out' : '')} onMouseDown={close}>
      <div className={'pf-drawer pf-form-panel st-drawer' + (closing ? ' out' : '')}
        onMouseDown={e => e.stopPropagation()} role="dialog" aria-label={title} aria-busy={submitting}>
        <div className="pf-drawer-head">
          <div>
            <div className="pf-drawer-eye mono">{eyebrow}</div>
            <div className="pf-drawer-title pf-form-title mono">{title}</div>
          </div>
          <button className="pf-x" onClick={close} aria-label="Close" disabled={submitting}>{Icons.close}</button>
        </div>

        <form className="pf-drawer-body" onSubmit={submit} noValidate>
          <FormRow label="Slug" req sub="lowercase · - _ · ≤32" error={!isEdit ? slugErr : null}>
            <input className={'pf-input mono' + (!isEdit && slugErr ? ' err' : '')} value={slug}
              onChange={e => setSlug(e.target.value)} placeholder="my-stack" maxLength={32}
              disabled={isEdit} data-testid="st-input-slug" />
          </FormRow>
          <FormRow label="Name" sub="display label">
            <input className="pf-input" value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="Coding" data-testid="st-input-name" />
          </FormRow>
          <FormRow label="Description" sub="what it's for">
            <textarea className="pf-input pf-textarea" rows={2} value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              placeholder="Fast coder + agentic muscle + repo retrieval" />
          </FormRow>
          <FormRow label="Icon" sub="emoji or accent">
            <input className="pf-input" value={form.icon}
              onChange={e => setForm(f => ({ ...f, icon: e.target.value }))} placeholder="⚡" maxLength={8} />
          </FormRow>
          <FormRow label="Tags" sub="comma-separated">
            <input className="pf-input mono" value={form.tags}
              onChange={e => setForm(f => ({ ...f, tags: e.target.value }))} placeholder="coding, fast" />
          </FormRow>

          <div className="st-slots-edit">
            <div className="pf-row-lbl" style={{ marginBottom: 6 }}>
              <span>Slots{slotErr && <span className="pf-msg err mono hint err" style={{ marginLeft: 8 }}>{Icons.alert}{slotErr}</span>}</span>
            </div>
            {form.slots.map((s, i) => (
              <div className="st-slot-edit" key={i}>
                <input className="pf-input mono st-slot-name" value={s.slot}
                  onChange={e => setSlot(i, 'slot', e.target.value)} placeholder="agent" maxLength={32}
                  data-testid={`st-slot-name-${i}`} />
                <select className="pf-input mono st-slot-model" value={s.model}
                  onChange={e => setSlot(i, 'model', e.target.value)} data-testid={`st-slot-model-${i}`}>
                  <option value="">— model —</option>
                  {models.map(m => <option key={m.id} value={m.id}>{m.id}</option>)}
                </select>
                <select className="pf-input mono st-slot-dev" value={s.device}
                  onChange={e => setSlot(i, 'device', e.target.value)}>
                  {DEVICES.map(d => <option key={d} value={d}>{DEVICE_META[d].label}</option>)}
                </select>
                <select className="pf-input mono st-slot-prof" value={s.profile}
                  onChange={e => setSlot(i, 'profile', e.target.value)}>
                  <option value="">— profile —</option>
                  {profiles.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
                </select>
                <button type="button" className={'pf-switch sm' + (s.mtp ? ' on' : '')}
                  onClick={() => setSlot(i, 'mtp', !s.mtp)} role="switch" aria-checked={s.mtp}
                  title="MTP speculative decode"><span className="pf-switch-knob" /><span className="mono">MTP</span></button>
                <button type="button" className="pf-btn danger" onClick={() => rmSlot(i)} title="Remove slot"
                  data-testid={`st-slot-rm-${i}`}>{Icons.trash}</button>
              </div>
            ))}
            <button type="button" className="pf-btn" onClick={addSlot} data-testid="st-slot-add">{Icons.plus} Add slot</button>
          </div>
        </form>

        <div className="pf-drawer-foot">
          <span className="pf-grow" />
          <button className="pf-btn" onClick={close} type="button" disabled={submitting}>Cancel</button>
          <button className="pf-btn primary" onClick={submit} disabled={submitting} data-testid="st-btn-submit">
            {submitting ? 'Saving…' : isEdit ? 'Save changes' : 'Create stack'}
          </button>
        </div>
      </div>
    </div>
  );
}

// A trimmed FormRow (Profiles' has bench-specific affordances we don't need).
function FormRow({ label, sub, req, children, error }) {
  return (
    <div className={'pf-row' + (error ? ' has-err' : '')}>
      <div className="pf-row-lbl">
        <span>{label}{req && <span className="pf-req" title="required">*</span>}</span>
        {sub && <span className="pf-row-sub mono">{sub}</span>}
      </div>
      <div className="pf-row-ctl">
        <div className={'pf-field' + (error ? ' err' : '')}>{children}</div>
        {error && <div className="pf-row-foot"><span className="pf-msg err mono hint err">{Icons.alert}{error}</span></div>}
      </div>
    </div>
  );
}

// ── Delete confirm ──────────────────────────────────────────────────────────

function DeleteConfirm({ s, onCancel, onConfirmed }) {
  const del = useStackDelete();
  const [busy, setBusy] = useState(false);
  async function handle() {
    setBusy(true);
    try {
      await del.mutateAsync(s.slug);
      toast(`Stack ${s.slug} deleted`, 'ok');
      onConfirmed();
    } catch (err) {
      toast(err?.code === 'stacks.seed_immutable' ? 'Seed stacks cannot be deleted' : (err?.message || 'Delete failed'), 'err');
      onCancel();
    } finally { setBusy(false); }
  }
  return (
    <div className="pf-scrim center pf-confirm-scrim" onMouseDown={() => { if (!busy) onCancel(); }}>
      <div className="pf-confirm" onMouseDown={e => e.stopPropagation()} role="dialog" aria-label="Confirm delete" aria-busy={busy}>
        <div className="pf-confirm-h pf-confirm-title mono">{Icons.trash} Delete · {s.slug}?</div>
        <div className="pf-confirm-b">
          <div className="pf-confirm-sub">This removes the stack permanently. Loaded slots are unaffected — only the saved bundle is deleted.</div>
        </div>
        <div className="pf-confirm-foot">
          <button className="pf-btn" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="pf-btn danger solid" onClick={handle} disabled={busy} data-testid="st-btn-delete-confirm">
            {busy ? 'Deleting…' : 'Delete stack'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Header / summary ────────────────────────────────────────────────────────

function Stat({ value, label, accent }) {
  return (
    <div className="pf-stat">
      <span className="pf-stat-v num" style={accent ? { color: accent } : null}>{value}</span>
      <span className="pf-stat-l mono">{label}</span>
    </div>
  );
}

function StacksHeader({ count, active, onNew, onImport, onSnapshot }) {
  return (
    <div className="engine-h pf-engine-h">
      <span className="engine-glyph">{Icons.slots}</span>
      <span className="cpane-titles">
        <span className="engine-title">Stacks</span>
        <span className="engine-sub">portable loadouts · slots + profiles + models, applied in one action</span>
      </span>
      {count != null && (
        <span className="cpill"><span className="dot" />{count} stack{count === 1 ? '' : 's'}</span>
      )}
      {active && <span className="cpill st-active-pill"><span className="dot" />active · {active}</span>}
      <span className="grow" />
      <span className="eh-right">
        <button className="pf-btn" onClick={onSnapshot} data-testid="st-btn-snapshot">{Icons.copy} Snapshot live</button>
        <button className="pf-btn" onClick={onImport} data-testid="st-btn-import">{Icons.download} Import</button>
        <button className="pf-btn primary" onClick={onNew} data-testid="st-btn-new">{Icons.plus} New stack</button>
      </span>
    </div>
  );
}

// ── Main view ───────────────────────────────────────────────────────────────

function StacksView() {
  const query = useStacks();
  const snapshot = useStackSnapshot();
  const data = query.data;
  const stacks = data?.stacks ?? [];

  const [drawer, setDrawer] = useState(null);    // {mode, source}
  const [confirm, setConfirm] = useState(null);
  const [applying, setApplying] = useState(null);
  const [importing, setImporting] = useState(false);

  const exportMut = useStackExport();

  const seeds = stacks.filter(s => s.seed);
  const custom = stacks.filter(s => !s.seed);

  async function onExport(s) {
    try {
      const env = await exportMut.mutateAsync(s.slug);
      const blob = new Blob([JSON.stringify(env, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `${s.slug}.hal0stack.json`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast(`Exported ${s.slug}`, 'ok');
    } catch (err) { toast(err?.message || 'Export failed', 'err'); }
  }

  async function onSnapshot() {
    try {
      const r = await snapshot.mutateAsync({ name: 'Snapshot' });
      // Open the editor prefilled with the live config for naming + saving.
      setDrawer({ mode: 'create', source: r.stack });
      toast('Captured live config — name it and save', 'info');
    } catch (err) { toast(err?.message || 'Snapshot failed', 'err'); }
  }

  if (query.isLoading) {
    return <div className="view"><div className="pf-engine"><StacksHeader /></div><div className="empty mono">Loading stacks…</div></div>;
  }
  if (query.isError) {
    return (
      <div className="view"><div className="pf-engine"><StacksHeader /></div>
        <div className="empty mono" style={{ color: 'var(--err)' }}>Failed to load stacks: {query.error?.message || 'unknown error'}</div>
      </div>
    );
  }

  const existing = stacks.map(s => s.slug);

  return (
    <div className="view">
      <div className="pf-engine">
        <StacksHeader count={stacks.length} active={data?.active}
          onNew={() => setDrawer({ mode: 'create' })}
          onImport={() => setImporting(true)}
          onSnapshot={onSnapshot} />
        <div className="pf-summary">
          <Stat value={stacks.length} label="stacks" />
          <span className="pf-stat-div" />
          <Stat value={seeds.length} label="seed templates" />
          <Stat value={custom.length} label="custom" accent="var(--accent)" />
          <span className="pf-stat-div" />
          <Stat value={data?.active || '—'} label="active"
            accent={data?.drift === 'modified' ? 'var(--warn)' : 'var(--ok)'} />
          {data?.active && data?.drift && <Stat value={data.drift} label="drift" />}
        </div>
      </div>

      {stacks.length === 0 ? (
        <div className="empty mono">No stacks yet — create one, snapshot the live config, or import a .hal0stack.json.</div>
      ) : (
        <>
          {seeds.length > 0 && (
            <Section title="Seed stacks" count={seeds.length} hint="immutable · ship with hal0">
              {seeds.map((s, i) => (
                <StackCard key={s.slug} s={s} index={i}
                  onApply={setApplying}
                  onClone={ss => setDrawer({ mode: 'clone', source: ss })}
                  onExport={onExport} onDelete={setConfirm} onEdit={() => {}} />
              ))}
            </Section>
          )}
          <Section title="Custom stacks" count={custom.length} hint="authored, cloned, snapshotted or imported on this box">
            {custom.length === 0
              ? <div className="empty mono" style={{ gridColumn: '1/-1' }}>None yet — clone a seed or snapshot the live config.</div>
              : custom.map((s, i) => (
                <StackCard key={s.slug} s={s} index={i}
                  onApply={setApplying}
                  onEdit={ss => setDrawer({ mode: 'edit', source: ss })}
                  onClone={ss => setDrawer({ mode: 'clone', source: ss })}
                  onExport={onExport} onDelete={setConfirm} />
              ))}
          </Section>
        </>
      )}

      {drawer && (
        <Drawer mode={drawer.mode} source={drawer.source} existing={existing}
          onClose={() => setDrawer(null)} onSaved={() => setDrawer(null)} />
      )}
      {confirm && <DeleteConfirm s={confirm} onCancel={() => setConfirm(null)} onConfirmed={() => setConfirm(null)} />}
      {applying && <ApplyModal stack={applying} onClose={() => setApplying(null)} />}
      {importing && <ImportModal existing={existing} onClose={() => setImporting(false)} onImported={() => setImporting(false)} />}
    </div>
  );
}

Object.assign(window, { StacksView });
