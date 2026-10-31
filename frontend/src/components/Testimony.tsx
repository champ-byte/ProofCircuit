import { useEffect, useRef, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { formatIst } from '../format'
import { confirmationLabel, formatMs, methodLabel } from '../testimony'
import type { DemoSession, VoiceNoteView, VoiceNotesResponse } from '../types/api'
import { useView } from '../view'

type Runner = (fn: () => Promise<unknown>, ok: string) => Promise<void>


function useAudioUrl(token: string, noteId: string): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let created: string | null = null
    let alive = true
    if (typeof URL.createObjectURL !== 'function') return
    api
      .voiceAudio(token, noteId)
      .then((blob) => {
        if (!alive) return
        created = URL.createObjectURL(blob)
        setUrl(created)
      })
      .catch(() => setUrl(null))
    return () => {
      alive = false
      if (created) URL.revokeObjectURL(created)
    }
  }, [token, noteId])
  return url
}

export function VoiceNoteCard({
  note,
  token,
  speaker,
  run,
}: {
  note: VoiceNoteView
  token: string
  speaker?: DemoSession // set only for the staff member who recorded it
  run?: Runner
}) {
  const { t } = useTranslation()
  const { detailed } = useView()
  const audioUrl = useAudioUrl(token, note.id)
  const audioRef = useRef<HTMLAudioElement>(null)
  const [draft, setDraft] = useState('')
  const [editing, setEditing] = useState(false)
  const cur = note.current
  const lang = (cur?.language ?? note.locale).split('-')[0]
  const canAct = Boolean(speaker && run && speaker.user.display_name === note.staff)
  const seek = (ms: number) => {
    const el = audioRef.current
    if (!el) return
    el.currentTime = ms / 1000
    el.focus()
  }
  return (
    <article className="voice-note" aria-label={t('testimony.noteFrom', { name: note.staff })}>
      <div className="sub">
        <Trans i18nKey="testimony.from" values={{ name: note.staff }} components={{ b: <strong /> }} /> · {detailed && <>{note.locale} · </>}{formatIst(note.created_at)}
        {note.staff_task && (
          <>
            {' '}
            · {t('testimony.answers', { what: t(`requirements.${note.staff_task.requirement_id}`, { defaultValue: note.staff_task.requirement_id.replaceAll('_', ' ') }), round: note.staff_task.round })}
          </>
        )}
      </div>
      <p className="testimony-note">
        <span className="tag">{t('testimony.tag')}</span> {detailed ? note.note : t('testimony.notProof')}
      </p>
      {audioUrl ? (
        <audio ref={audioRef} controls src={audioUrl} preload="metadata" aria-label={t('testimony.audioLabel')} />
      ) : (
        <p className="sub">{t('testimony.audioLoading')}</p>
      )}
      {!detailed && <p className="sub">{t(`testimony.stt.${note.stt_status}`)}</p>}
      {detailed && <dl className="kv">
        <dt>Audio SHA-256</dt>
        <dd className="mono">{note.sha256.slice(0, 16)}…</dd>
        <dt>{t('testimony.file')}</dt>
        <dd>
          {note.original_filename} · {note.mime_type} · {note.size_bytes.toLocaleString('en-IN')} bytes
          {note.duration_ms != null && <> · {formatMs(note.duration_ms)}</>}
        </dd>
        <dt>{t('testimony.sttLabel')}</dt>
        <dd>
          {t(`testimony.stt.${note.stt_status}`)}
          {note.stt_detail && <span className="sub"> — {note.stt_detail}</span>}
        </dd>
      </dl>}
      {cur ? (
        <div className="transcript">
          <div className="sub">
            {detailed && <>{t('testimony.transcript', { version: cur.version })} · {methodLabel(cur)}
            {cur.language && cur.method === 'stt' && <> · {t('testimony.language', { lang: cur.language })}</>} ·{' '}</>}
            <strong>{confirmationLabel(cur, note.staff)}</strong>
            {!cur.text_recheck_ok && <span className="warn"> · {t('testimony.hashMismatch')}</span>}
          </div>
          {cur.timestamps_available ? (
            <ol className="segments" lang={lang}>
              {cur.segments.map((s) => (
                <li key={s.start}>
                  <button
                    type="button"
                    className="link mono"
                    onClick={() => seek(s.audio_start_ms)}
                    aria-label={t('testimony.playFrom', { time: formatMs(s.audio_start_ms) })}
                  >
                    {formatMs(s.audio_start_ms)}–{formatMs(s.audio_end_ms)}
                  </button>
                  {!s.timestamp_in_range && (
                    <span className="warn"> {t('testimony.beyond')}</span>
                  )}{' '}
                  {s.text}
                </li>
              ))}
            </ol>
          ) : (
            <>
              <blockquote lang={lang}>{cur.text}</blockquote>
              {detailed && <p className="sub">{t('testimony.noTimestamps')}</p>}
            </>
          )}
          {detailed && note.versions.length > 1 && (
            <details>
              <summary>{t('testimony.history', { count: note.versions.length })}</summary>
              <ol className="timeline">
                {note.versions.map((v) => (
                  <li key={v.id}>
                    v{v.version} · {methodLabel(v)} · {v.confirmation_state} · <span lang={lang}>{v.text}</span>
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
      ) : (
        <p className="sub">{t('testimony.noTranscript')}</p>
      )}
      {canAct && speaker && run && (
        <div className="voice-actions">
          {cur?.confirmation_state === 'unconfirmed' && !editing && (
            <button
              type="button"
              onClick={() =>
                run(() => api.confirmTranscript(speaker.token, note.id, cur.version), t('testimony.confirmed'))
              }
            >
              {t('testimony.confirm')}
            </button>
          )}
          {cur && !editing && (
            <button
              type="button"
              onClick={() => {
                setDraft(cur.text)
                setEditing(true)
              }}
            >
              {t('testimony.correct')}
            </button>
          )}
          {!cur && (note.stt_status === 'stt_unavailable' || note.stt_status === 'stt_failed') && !editing && (
            <button type="button" onClick={() => setEditing(true)}>
              {t('testimony.typeIt')}
            </button>
          )}
          {editing && (
            <form
              className="reply"
              onSubmit={(e) => {
                e.preventDefault()
                if (!draft.trim()) return
                void run(
                  async () => {
                    if (cur) await api.correctTranscript(speaker.token, note.id, cur.version, draft)
                    else await api.transcribeManually(speaker.token, note.id, draft)
                    setEditing(false)
                  },
                  cur ? t('testimony.correctionSaved') : t('testimony.humanSaved'),
                )
              }}
            >
              <label>
                {cur ? t('testimony.corrected') : t('testimony.whatYouSaid')}
                <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} lang={lang} />
              </label>
              <button type="submit">{t('testimony.save')}</button>
              <button type="button" onClick={() => setEditing(false)}>
                {t('testimony.cancel')}
              </button>
            </form>
          )}
        </div>
      )}
    </article>
  )
}

/** Workspace panel: every voice note with its provenance; read-only. */
export function TestimonyPanel({ caseId, token, version }: { caseId: string; token: string; version: number }) {
  const { t } = useTranslation()
  const { detailed } = useView()
  const [data, setData] = useState<VoiceNotesResponse | null>(null)
  useEffect(() => {
    api
      .voiceNotes(token, caseId)
      .then(setData)
      .catch(() => setData(null))
  }, [token, caseId, version])
  if (!data) return null
  return (
    <section aria-labelledby="testimony-h" className="panel">
      <div className="panel-head">
        <h2 id="testimony-h">{t('testimony.panelTitle')}</h2>
        {detailed && <span className="sub">{t('testimony.sttStatus', { status: data.speech.available ? data.speech.provider : t('testimony.unavailable') })}</span>}
      </div>
      <p className="sub">{t('testimony.panelNote')}</p>
      {data.voice_notes.length === 0 ? (
        <p className="empty">{t('testimony.none')}</p>
      ) : (
        data.voice_notes.map((n) => <VoiceNoteCard key={n.id} note={n} token={token} />)
      )}
    </section>
  )
}

/** Drawer controls for the acting staff member: send a voice note, confirm or correct the transcript. */
export function StaffVoiceNotes({
  caseId,
  staff,
  version,
  run,
}: {
  caseId: string
  staff: DemoSession
  version: number
  run: Runner
}) {
  const { t } = useTranslation()
  const [data, setData] = useState<VoiceNotesResponse | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    api
      .voiceNotes(staff.token, caseId)
      .then(setData)
      .catch(() => setData(null))
  }, [staff.token, caseId, version])
  const mine = (data?.voice_notes ?? []).filter((n) => n.staff === staff.user.display_name)
  return (
    <div className="staff-voice">
      <h3>{t('testimony.voiceNotes')}</h3>
      <p className="sub">
        {t('testimony.sttStatus', {
          status: data
            ? data.speech.available
              ? t('testimony.sttLocal', { provider: data.speech.provider })
              : t('testimony.sttUnavailable', { detail: data.speech.detail })
            : '…',
        })}
      </p>
      <div className="fixture-buttons">
        <label>
          {t('testimony.sendAs', { name: staff.user.display_name })}
          <input
            ref={fileRef}
            type="file"
            accept=".wav,.ogg,.opus,.mp3,.m4a,.webm,audio/*"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (!file) return
              void run(async () => {
                await api.uploadVoiceNote(staff.token, caseId, file, file.name)
                if (fileRef.current) fileRef.current.value = ''
              }, t('testimony.sent'))
            }}
          />
        </label>
        <button
          type="button"
          onClick={() =>
            run(async () => {
              const blob = await api.voiceFixture(staff.token, caseId)
              await api.uploadVoiceNote(staff.token, caseId, blob, 'voice_note_mr.ogg')
            }, t('testimony.demoSent'))
          }
        >
          {t('testimony.demo')}
        </button>
      </div>
      {mine.map((n) => (
        <VoiceNoteCard key={n.id} note={n} token={staff.token} speaker={staff} run={run} />
      ))}
    </div>
  )
}
