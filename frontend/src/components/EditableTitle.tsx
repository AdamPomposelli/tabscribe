import { useEffect, useRef, useState } from 'react'

/** Title that turns into a text field on double-click (Enter saves, Escape cancels). */
export function EditableTitle({ value, onSave, className, as = 'div' }: {
  value: string; onSave: (v: string) => void; className?: string; as?: 'div' | 'h1'
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { if (!editing) setDraft(value) }, [value, editing])
  useEffect(() => { if (editing) { ref.current?.focus(); ref.current?.select() } }, [editing])

  const commit = () => {
    setEditing(false)
    const v = draft.trim()
    if (v && v !== value) onSave(v)
    else setDraft(value)
  }

  if (editing) {
    return (
      <input ref={ref} className={`${className ?? ''} title-input`} value={draft} maxLength={200}
        onChange={e => setDraft(e.target.value)} onBlur={commit}
        onKeyDown={e => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') { setDraft(value); setEditing(false) }
        }} />
    )
  }
  const Tag = as
  return (
    <Tag className={`${className ?? ''} editable`} title="Double-click to rename" onDoubleClick={() => setEditing(true)}>
      {value}
    </Tag>
  )
}
