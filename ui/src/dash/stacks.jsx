// hal0 dashboard — Stacks view (Focus layout).
//
// A Stack is a named, portable bundle of slots + their profiles + model
// assignments. The Focus layout (design handoff: stacks_overhaul) surfaces the
// currently-applied stack as a full-width hero with per-slot live state, then
// lists the rest as a compact library grid below — keeping attention on what's
// running while giving fast access to swap.
//
// Real data: GET /api/stacks (useStacks) + live slot state (useSlots) + the
// local registry (useModels, for "model not available → pull"). Load goes
// through the real apply (commit + converge, create-on-apply); Pull starts a
// real model pull job; Export downloads the portable envelope; Import / New /
// Snapshot reuse the existing flows. Styles: .stk-* in stacks.css.

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
import { useSlots } from '@/api/hooks/useSlots'
import { api } from '@/api/client'
import { ENDPOINTS } from '@/api/endpoints'

// Device hue, for the editor selectors.
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

const DOT_STATES = new Set(['serving', 'ready', 'warming', 'idle', 'offline']);
function dotCls(state) { return DOT_STATES.has(state) ? state : 'offline'; }

function toast(msg, kind = 'info') {
  if (typeof window !== 'undefined' && window.__hal0Toast) window.__hal0Toast(msg, kind);
}

// ── status dot ────────────────────────────────────────────────────────────────

function D({ state, sz = 6 }) {
  return <span className={'dot ' + dotCls(state)} style={{ width: sz, height: sz, flexShrink: 0 }} />;
}

// ── view-model: project a stack into the Focus shape ──────────────────────────
// slots: [{ name, model, profile, state, available }]. `state` is the live slot
// status for the active stack, "offline" otherwise. `available` is false only
// when a referenced model isn't in the local registry (→ pull affordance).

function buildVM(stack, modelSet, liveByName, activeSlug) {
  const active = stack.slug === activeSlug;
  const slots = [];
  for (const sl of stack.slots || []) {
    if (sl.model) {
      slots.push({
        name: sl.slot,
        model: sl.model,
        profile: sl.profile || sl.device || '',
        state: active ? dotCls(liveByName[sl.slot]?.status) : 'offline',
        available: modelSet.has(sl.model),
      });
    }
    for (const row of sl.capabilities || []) {
      if (!row.model) continue;
      slots.push({
        name: row.child,
        model: row.model,
        profile: row.device || '',
        state: 'offline',
        available: modelSet.has(row.model),
      });
    }
  }
  return {
    id: stack.slug,
    slug: stack.slug,
    name: stack.name || stack.slug,
    intent: stack.description || '',
    seed: !!stack.seed,
    active,
    drift: active ? (stack.drift || 'clean') : null,
    tags: stack.tags || [],
    slots,
  };
}

function missingCount(vm) { return vm.slots.filter(s => !s.available).length; }

// ── Pull-missing-models dialog ────────────────────────────────────────────────

function PullDialog({ vm, onPull, pulled, onClose }) {
  const missing = vm.slots.filter(s => !s.available);
  return (
    <div className="stk-scrim" onMouseDown={onClose}>
      <div className="stk-dialog" onMouseDown={e => e.stopPropagation()} role="dialog" aria-label="Pull missing models">
        <div className="stk-dlg-h">
          <span className="stk-dlg-eye">Pull missing models · {vm.name}</span>
          <button className="stk-dlg-x" onClick={onClose} aria-label="Close">{Icons.close}</button>
        </div>
        <div className="stk-dlg-b">
          <div className="stk-dlg-hint">
            These models aren't available locally. Pull them before loading this stack.
          </div>
          {missing.map(s => {
            const done = pulled.includes(s.model);
            return (
              <div key={s.name + s.model} className="stk-pull-item">
                <span className="stk-pull-slot">{s.name}</span>
                <span className="stk-pull-model">{s.model}</span>
                {done
                  ? <span className="stk-pull-done">{Icons.check} queued</span>
                  : <button className="btn sm" onClick={() => onPull(s.model)}>{Icons.download} Pull</button>}
              </div>
            );
          })}
        </div>
        <div className="stk-dlg-f">
          <button className="btn ghost sm" onClick={onClose}>Close</button>
          {missing.some(s => !pulled.includes(s.model)) && (
            <button className="btn sm" onClick={() => missing.forEach(s => onPull(s.model))}>
              Queue all {missing.length}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Load-stack confirm dialog ─────────────────────────────────────────────────

function LoadDialog({ vm, onLoad, onPull, busy, onClose }) {
  const missing = vm.slots.filter(s => !s.available);
  const hasMissing = missing.length > 0;
  return (
    <div className="stk-scrim" onMouseDown={() => { if (!busy) onClose(); }}>
      <div className="stk-dialog" onMouseDown={e => e.stopPropagation()} role="dialog" aria-label="Load stack" aria-busy={busy}>
        <div className="stk-dlg-h">
          <span className="stk-dlg-eye">Load stack</span>
          <button className="stk-dlg-x" onClick={onClose} aria-label="Close" disabled={busy}>{Icons.close}</button>
        </div>
        <div className="stk-dlg-b">
          <div>
            <div className="stk-dlg-stack">{vm.name}</div>
            <div className="stk-dlg-hint" style={{ marginTop: 4 }}>{vm.intent}</div>
          </div>
          {hasMissing && (
            <div className="stk-dlg-warn">
              {Icons.alert}
              {missing.length} model{missing.length > 1 ? 's' : ''} not found locally — those slots are skipped unless pulled first.
            </div>
          )}
          <div className="stk-slot-list">
            {vm.slots.map(s => (
              <div key={s.name + s.model} className={'stk-slot-row' + (!s.available ? ' miss' : '')}>
                <D state={s.available ? 'ready' : 'offline'} sz={6} />
                <span className="sname">{s.name}</span>
                <span className="smodel">{s.model}</span>
                {!s.available && <span className="smiss">not found</span>}
              </div>
            ))}
          </div>
        </div>
        <div className="stk-dlg-f">
          <button className="btn ghost sm" onClick={onClose} disabled={busy}>Cancel</button>
          {hasMissing && (
            <button className="btn sm" style={{ background: 'transparent', color: 'var(--warn)', borderColor: 'var(--warn-line)' }}
              onClick={() => { onClose(); onPull(vm); }} disabled={busy}>
              Pull missing first
            </button>
          )}
          <button className="btn sm" onClick={() => onLoad(vm)} disabled={busy} data-testid="st-load-confirm">
            {busy ? 'Loading…' : hasMissing ? 'Load anyway' : 'Load stack'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Focus hero (active stack) ─────────────────────────────────────────────────

function HeroPanel({ vm, isCustom, onPull, onExport, onReapply, onEdit }) {
  const miss = missingCount(vm);
  return (
    <div className="stk-hero">
      <div className="stk-hero-h">
        <div>
          <div className="stk-hero-eye">Active stack</div>
          <div className="stk-hero-name">{vm.name}</div>
          <div className="stk-hero-intent">{vm.intent || 'no description'}</div>
        </div>
        <div className="stk-hero-meta">
          <span className="stk-badge live"><D state="serving" sz={6} />running</span>
          <span className="stk-hero-ver">{vm.drift === 'modified' ? 'modified since apply' : 'clean'}</span>
        </div>
      </div>
      <div className="stk-hero-slots">
        {vm.slots.map(s => (
          <div key={s.name + s.model} className="stk-hero-slot">
            <div className="stk-hs-row">
              <D state={s.state} sz={7} />
              <span className="stk-hs-name">{s.name}</span>
              <span className={'stk-hs-state ' + s.state}>{s.available ? s.state : 'no model'}</span>
            </div>
            <div className="stk-hs-profile">{s.profile}</div>
            <div className="stk-hs-model">{s.model}</div>
          </div>
        ))}
      </div>
      <div className="stk-hero-f">
        <div className="stk-hero-tags">
          {vm.tags.map(t => <span key={t} className="stk-tag">{t}</span>)}
          <span className="stk-tag shared">{vm.seed ? 'seed' : 'custom'}</span>
        </div>
        <span className="stk-spacer" />
        {miss > 0 && (
          <button className="stk-missing-btn" onClick={() => onPull(vm)}>{Icons.alert} {miss} missing</button>
        )}
        {isCustom && <button className="btn ghost sm" onClick={() => onEdit(vm)}>{Icons.edit} Edit</button>}
        <button className="btn ghost sm" onClick={() => onExport(vm)}>{Icons.download} Export</button>
        <button className="btn sm" onClick={() => onReapply(vm)} data-testid={`st-reapply-${vm.slug}`}>Re-apply</button>
      </div>
    </div>
  );
}

// ── Library card (inactive stacks) ────────────────────────────────────────────

function LibCard({ vm, idx, isCustom, onLoad, onPull, onExport, onClone, onEdit, onDelete }) {
  const miss = missingCount(vm);
  return (
    <div className="stk-lib-card" style={{ animationDelay: idx * 35 + 'ms' }}>
      <div className="stk-lib-h">
        <div className="stk-lib-id">
          <div className="stk-lib-name">{vm.name}</div>
          <div className="stk-lib-intent">{vm.intent || 'no description'}</div>
        </div>
        <span className="mono" style={{ fontSize: 9.5, color: 'var(--fg-5)', paddingTop: 2, flexShrink: 0 }}>
          {vm.seed ? 'seed' : 'custom'}
        </span>
      </div>
      <div className="stk-lib-slotlist">
        {vm.slots.map(s => (
          <div key={s.name + s.model} className={'stk-lib-slotrow' + (!s.available ? ' miss' : '')}>
            <D state="offline" sz={5} />
            <span className="stk-csr-name mono">{s.name}</span>
            <span className="stk-csr-model mono">{s.model}</span>
            {!s.available && Icons.alert}
          </div>
        ))}
        {vm.slots.length === 0 && <div className="stk-lib-slotrow"><span className="stk-csr-model mono" style={{ color: 'var(--fg-5)' }}>no slots</span></div>}
      </div>
      <div className="stk-lib-f">
        {miss > 0 && (
          <button className="stk-missing-btn sm" onClick={() => onPull(vm)}>{Icons.alert} {miss} missing</button>
        )}
        <span className="stk-spacer" />
        <button className="stk-icon-btn" style={{ width: 26, height: 26 }} title="Clone" onClick={() => onClone(vm)}>{Icons.copy}</button>
        {isCustom && (
          <>
            <button className="stk-icon-btn" style={{ width: 26, height: 26 }} title="Edit" onClick={() => onEdit(vm)}>{Icons.edit}</button>
            <button className="stk-icon-btn" style={{ width: 26, height: 26 }} title="Delete" onClick={() => onDelete(vm)}>{Icons.trash}</button>
          </>
        )}
        <button className="stk-icon-btn" style={{ width: 26, height: 26 }} title="Export" onClick={() => onExport(vm)}>{Icons.download}</button>
        <button className="btn sm" onClick={() => onLoad(vm)} data-testid={`st-load-${vm.slug}`}>Load</button>
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
    <div className="stk-scrim" onMouseDown={() => { if (!busy) onClose(); }}>
      <div className="stk-dialog" onMouseDown={e => e.stopPropagation()} role="dialog" aria-label="Import stack">
        <div className="stk-dlg-h">
          <span className="stk-dlg-eye">Import stack</span>
          <button className="stk-dlg-x" onClick={onClose} aria-label="Close" disabled={busy}>{Icons.close}</button>
        </div>
        <div className="stk-dlg-b">
          {!report ? (
            <label className="stk-drop">
              <input type="file" accept=".json,application/json" style={{ display: 'none' }}
                onChange={e => e.target.files?.[0] && onFile(e.target.files[0])} data-testid="st-import-file" />
              <span className="stk-drop-glyph">{Icons.attach}</span>
              <span className="mono">Choose a .hal0stack.json file</span>
              {err && <span className="stk-dlg-warn">{Icons.alert}{err}</span>}
            </label>
          ) : (
            <>
              <div className="stk-dlg-hint">
                {report.name || 'stack'} · schema v{report.schema_version} · checksum {report.checksum_ok ? 'ok' : '⚠ mismatch'}
              </div>
              <div className="stk-slot-list">
                {(report.resolutions || []).map(r => (
                  <div key={r.model_id} className={'stk-slot-row' + (r.status === 'unresolvable' ? ' miss' : '')}>
                    <span className="smodel">{r.model_id}</span>
                    <span className="smiss" style={{ color: r.status === 'present' ? 'var(--ok)' : r.status === 'pullable' ? 'var(--info)' : 'var(--err)' }}>{r.status}</span>
                  </div>
                ))}
                {(!report.resolutions || report.resolutions.length === 0) && (
                  <div className="stk-dlg-hint" style={{ color: 'var(--fg-5)' }}>no model references</div>
                )}
              </div>
              {report.unresolvable?.length > 0 && (
                <div className="stk-dlg-warn">{Icons.alert}{report.unresolvable.length} model(s) unresolvable — those slots import disabled.</div>
              )}
              <div className="stk-slot-list">
                <div className="stk-slot-row">
                  <span className="sname">Save as</span>
                  <input className={'pf-input mono' + (slug && !slugValid ? ' err' : '')} value={slug}
                    onChange={e => setSlug(e.target.value)} maxLength={32} placeholder="my-stack"
                    style={{ flex: 1, background: 'transparent', border: 'none', color: 'var(--fg)', fontFamily: 'var(--jbm)' }}
                    data-testid="st-import-slug" />
                </div>
              </div>
              {slugTaken && <div className="stk-dlg-warn">{Icons.alert}“{slug}” already exists</div>}
            </>
          )}
        </div>
        <div className="stk-dlg-f">
          <button className="btn ghost sm" onClick={onClose} disabled={busy}>Cancel</button>
          {report && (
            <button className="btn sm" onClick={commit} disabled={!slugValid || busy} data-testid="st-import-confirm">
              {busy ? 'Importing…' : 'Import'}
            </button>
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
    description: s.description || s.intent || '',
    icon: s.icon || '',
    tags: (s.tags || []).join(', '),
    slots: (s.slots || []).map(e => ({
      slot: e.slot || e.name || '',
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
  const liveSlots = (useSlots().data || []).filter(s => (s.kind ?? 'local') === 'local');

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

  const setSlot = (i, k, v) => setForm(f => ({ ...f, slots: f.slots.map((s, j) => j === i ? { ...s, [k]: v } : s) }));
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
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Coding" data-testid="st-input-name" />
          </FormRow>
          <FormRow label="Description" sub="what it's for">
            <textarea className="pf-input pf-textarea" rows={2} value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              placeholder="Fast coder + agentic muscle + repo retrieval" />
          </FormRow>
          <FormRow label="Tags" sub="comma-separated">
            <input className="pf-input mono" value={form.tags}
              onChange={e => setForm(f => ({ ...f, tags: e.target.value }))} placeholder="coding, fast" />
          </FormRow>

          <div className="st-slots-edit">
            <div className="pf-row-lbl" style={{ marginBottom: 6 }}>
              <span>Slots{slotErr && <span className="pf-msg err mono hint err" style={{ marginLeft: 8 }}>{Icons.alert}{slotErr}</span>}</span>
            </div>
            <datalist id="st-existing-slots">
              {liveSlots.map(s => <option key={s.name} value={s.name} />)}
            </datalist>
            {form.slots.map((s, i) => {
              const isNew = !!s.slot && !liveSlots.some(ls => ls.name === s.slot);
              return (
                <div className="st-slot-edit" key={i}>
                  <input className="pf-input mono st-slot-name" value={s.slot} list="st-existing-slots"
                    onChange={e => setSlot(i, 'slot', e.target.value)} placeholder="pick or name…" maxLength={32}
                    title={isNew ? 'New slot — created on apply' : 'Existing slot'} data-testid={`st-slot-name-${i}`} />
                  {isNew && <span className="st-slot-new mono" title="Created on apply">new</span>}
                  <select className="pf-input mono st-slot-model" value={s.model}
                    onChange={e => setSlot(i, 'model', e.target.value)} data-testid={`st-slot-model-${i}`}>
                    <option value="">— model —</option>
                    {models.map(m => <option key={m.id} value={m.id}>{m.id}</option>)}
                  </select>
                  <select className="pf-input mono st-slot-dev" value={s.device} onChange={e => setSlot(i, 'device', e.target.value)}>
                    {DEVICES.map(d => <option key={d} value={d}>{DEVICE_META[d].label}</option>)}
                  </select>
                  <select className="pf-input mono st-slot-prof" value={s.profile} onChange={e => setSlot(i, 'profile', e.target.value)}>
                    <option value="">— profile —</option>
                    {profiles.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
                  </select>
                  <button type="button" className={'pf-switch sm' + (s.mtp ? ' on' : '')}
                    onClick={() => setSlot(i, 'mtp', !s.mtp)} role="switch" aria-checked={s.mtp} title="MTP speculative decode">
                    <span className="pf-switch-knob" /><span className="mono">MTP</span>
                  </button>
                  <button type="button" className="pf-btn danger" onClick={() => rmSlot(i)} title="Remove slot" data-testid={`st-slot-rm-${i}`}>{Icons.trash}</button>
                </div>
              );
            })}
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

function DeleteConfirm({ vm, onCancel, onConfirmed }) {
  const del = useStackDelete();
  const [busy, setBusy] = useState(false);
  async function handle() {
    setBusy(true);
    try {
      await del.mutateAsync(vm.slug);
      toast(`Stack ${vm.slug} deleted`, 'ok');
      onConfirmed();
    } catch (err) {
      toast(err?.code === 'stacks.seed_immutable' ? 'Seed stacks cannot be deleted' : (err?.message || 'Delete failed'), 'err');
      onCancel();
    } finally { setBusy(false); }
  }
  return (
    <div className="stk-scrim" onMouseDown={() => { if (!busy) onCancel(); }}>
      <div className="stk-dialog" style={{ maxWidth: 420 }} onMouseDown={e => e.stopPropagation()} role="dialog" aria-label="Confirm delete" aria-busy={busy}>
        <div className="stk-dlg-h"><span className="stk-dlg-eye">Delete · {vm.slug}?</span>
          <button className="stk-dlg-x" onClick={onCancel} aria-label="Close" disabled={busy}>{Icons.close}</button>
        </div>
        <div className="stk-dlg-b">
          <div className="stk-dlg-hint">This removes the stack permanently. Loaded slots are unaffected — only the saved bundle is deleted.</div>
        </div>
        <div className="stk-dlg-f">
          <button className="btn ghost sm" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="btn sm" style={{ background: 'transparent', color: 'var(--err)', borderColor: 'var(--err-line)' }}
            onClick={handle} disabled={busy} data-testid="st-btn-delete-confirm">{busy ? 'Deleting…' : 'Delete stack'}</button>
        </div>
      </div>
    </div>
  );
}

// ── Main view ───────────────────────────────────────────────────────────────

function StacksView() {
  const query = useStacks();
  const slotsQuery = useSlots();
  const modelsQuery = useModels();
  const snapshot = useStackSnapshot();
  const apply = useStackApply();
  const exportMut = useStackExport();

  const data = query.data;
  const rawStacks = data?.stacks ?? [];

  const [drawer, setDrawer] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const [loadTgt, setLoadTgt] = useState(null);
  const [pullTgt, setPullTgt] = useState(null);
  const [pulledQ, setPulledQ] = useState([]);
  const [importing, setImporting] = useState(false);
  const [loadBusy, setLoadBusy] = useState(false);

  const modelSet = new Set((modelsQuery.data ?? []).map(m => m.id));
  const liveByName = {};
  for (const s of slotsQuery.data ?? []) liveByName[s.name] = s;

  const vms = rawStacks.map(s => buildVM(s, modelSet, liveByName, data?.active));
  const activeVM = vms.find(v => v.active) || null;
  const library = vms.filter(v => !v.active);
  const totalMiss = vms.reduce((n, v) => n + missingCount(v), 0);
  const existing = rawStacks.map(s => s.slug);
  const isCustom = (vm) => !vm.seed;

  async function onExport(vm) {
    try {
      const env = await exportMut.mutateAsync(vm.slug);
      const blob = new Blob([JSON.stringify(env, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = `${vm.slug}.hal0stack.json`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast(`Exported ${vm.slug}`, 'ok');
    } catch (err) { toast(err?.message || 'Export failed', 'err'); }
  }

  async function onSnapshot() {
    try {
      const r = await snapshot.mutateAsync({ name: 'Snapshot' });
      setDrawer({ mode: 'create', source: r.stack });
      toast('Captured live config — name it and save', 'info');
    } catch (err) { toast(err?.message || 'Snapshot failed', 'err'); }
  }

  function openPull(vm) { setPulledQ([]); setPullTgt(vm); }

  async function queuePull(model) {
    setPulledQ(q => q.includes(model) ? q : [...q, model]);
    try {
      await api(ENDPOINTS.modelPull(model), { method: 'POST', raw: true });
      toast(`Pulling ${model}…`, 'info');
    } catch (err) {
      toast(err?.message || `Pull failed: ${model}`, 'err');
    }
  }

  async function confirmLoad(vm) {
    setLoadBusy(true);
    try {
      const r = await apply.mutateAsync({ slug: vm.slug, dryRun: false });
      const errs = r?.converged?.errors?.length || 0;
      toast(errs ? `Loaded ${vm.name} with ${errs} slot error(s)` : `Stack “${vm.name}” loaded`, errs ? 'warn' : 'ok');
      setLoadTgt(null);
    } catch (err) {
      toast(err?.message || 'Load failed', 'err');
    } finally { setLoadBusy(false); }
  }

  if (query.isLoading) {
    return <div className="view"><Header /><div className="empty mono" style={{ marginTop: 20 }}>Loading stacks…</div></div>;
  }
  if (query.isError) {
    return (
      <div className="view"><Header />
        <div className="empty mono" style={{ marginTop: 20, color: 'var(--err)' }}>Failed to load stacks: {query.error?.message || 'unknown error'}</div>
      </div>
    );
  }

  function Header() {
    return (
      <div className="vh">
        <span className="vh-eye mono">RUNTIME</span>
        <h1>Stacks</h1>
        <div className="vh-spacer" />
        <span className="hint mono">preconfigured slot + profile + model bundles</span>
        <button className="btn ghost sm" onClick={() => setImporting(true)} data-testid="st-btn-import">{Icons.attach} Import</button>
        <button className="btn ghost sm" onClick={onSnapshot} data-testid="st-btn-snapshot">{Icons.copy} Snapshot</button>
        <button className="btn sm" onClick={() => setDrawer({ mode: 'create' })} data-testid="st-btn-new">{Icons.plus} New stack</button>
      </div>
    );
  }

  const libProps = {
    isCustomFn: isCustom,
    onLoad: setLoadTgt, onPull: openPull, onExport,
    onClone: vm => setDrawer({ mode: 'clone', source: rawStacks.find(s => s.slug === vm.slug) }),
    onEdit: vm => setDrawer({ mode: 'edit', source: rawStacks.find(s => s.slug === vm.slug) }),
    onDelete: setConfirm,
  };

  return (
    <div className="view">
      <Header />

      <div className="stk-toolbar">
        <div className="stk-summary">
          <span className="stk-sum-item"><b className="num">{vms.length}</b><span className="mono"> stacks</span></span>
          <span className="stk-sum-sep">·</span>
          <span className="stk-sum-item"><b className="num" style={{ color: activeVM ? 'var(--ok)' : 'var(--fg-4)' }}>{activeVM ? 1 : 0}</b><span className="mono"> active</span></span>
          {totalMiss > 0 && <>
            <span className="stk-sum-sep">·</span>
            <span className="stk-sum-item"><b className="num" style={{ color: 'var(--warn)' }}>{totalMiss}</b><span className="mono"> missing models</span></span>
          </>}
        </div>
      </div>

      {vms.length === 0 ? (
        <div className="empty mono">No stacks yet — create one, snapshot the live config, or import a .hal0stack.json.</div>
      ) : (
        <div className="stk-focus">
          {activeVM
            ? <HeroPanel vm={activeVM} isCustom={isCustom(activeVM)} onPull={openPull} onExport={onExport}
                onReapply={setLoadTgt} onEdit={libProps.onEdit} />
            : <div className="stk-hero" style={{ borderColor: 'var(--line)' }}>
                <div className="stk-hero-h">
                  <div>
                    <div className="stk-hero-eye">No active stack</div>
                    <div className="stk-hero-name" style={{ color: 'var(--fg-3)' }}>Nothing applied</div>
                    <div className="stk-hero-intent">Load a stack below to set the platform's models, embed, and voice in one action.</div>
                  </div>
                </div>
              </div>}

          <div className="sec" style={{ marginTop: 28, marginBottom: 14 }}>
            <h2>Library <span className="ct num">{library.length}</span></h2>
            <span className="rule" />
          </div>

          {library.length === 0
            ? <div className="empty mono">Every stack is the active one. Clone a seed or snapshot the live config to add more.</div>
            : <div className="stk-lib-grid">
                {library.map((vm, i) => (
                  <LibCard key={vm.slug} vm={vm} idx={i} isCustom={isCustom(vm)}
                    onLoad={libProps.onLoad} onPull={libProps.onPull} onExport={libProps.onExport}
                    onClone={libProps.onClone} onEdit={libProps.onEdit} onDelete={libProps.onDelete} />
                ))}
              </div>}
        </div>
      )}

      {drawer && <Drawer mode={drawer.mode} source={drawer.source} existing={existing}
        onClose={() => setDrawer(null)} onSaved={() => setDrawer(null)} />}
      {confirm && <DeleteConfirm vm={confirm} onCancel={() => setConfirm(null)} onConfirmed={() => setConfirm(null)} />}
      {loadTgt && <LoadDialog vm={loadTgt} busy={loadBusy} onLoad={confirmLoad} onPull={openPull} onClose={() => setLoadTgt(null)} />}
      {pullTgt && <PullDialog vm={pullTgt} pulled={pulledQ} onPull={queuePull} onClose={() => setPullTgt(null)} />}
      {importing && <ImportModal existing={existing} onClose={() => setImporting(false)} onImported={() => setImporting(false)} />}
    </div>
  );
}

Object.assign(window, { StacksView });
