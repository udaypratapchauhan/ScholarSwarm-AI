import React, { useState } from 'react';
import { 
  Copy, 
  Check, 
  Download, 
  CheckSquare, 
  Square, 
  HelpCircle, 
  AlertCircle, 
  Sparkles, 
  BookOpen
} from 'lucide-react';
import type { SOPDraft } from '../types';

interface SOPViewerProps {
  sop: SOPDraft | null;
  loading: boolean;
}

export const SOPViewer: React.FC<SOPViewerProps> = ({ sop, loading }) => {
  const [copied, setCopied] = useState(false);
  const [editableText, setEditableText] = useState(sop?.sop_text || '');
  const [checkedItems, setCheckedItems] = useState<Record<number, boolean>>({});

  // Sync state if sop changes
  React.useEffect(() => {
    if (sop) {
      setEditableText(sop.sop_text);
    }
  }, [sop]);

  if (loading) {
    return (
      <div style={{ maxWidth: '980px', margin: '48px auto', textAlign: 'center', color: '#94a3b8' }}>
        <p>Loading generated Statement of Purpose & Application Checklist...</p>
      </div>
    );
  }

  if (!sop) {
    return (
      <div className="card-container" style={{ maxWidth: '780px', margin: '48px auto', padding: '40px', textAlign: 'center' }}>
        <AlertCircle size={36} color="#f59e0b" style={{ margin: '0 auto 12px' }} />
        <h3 style={{ fontSize: '1.25rem', fontWeight: '800', color: '#ffffff', marginBottom: '8px' }}>
          No Statement of Purpose Generated Yet
        </h3>
        <p style={{ color: '#94a3b8', fontSize: '0.9375rem', maxWidth: '520px', margin: '0 auto 20px' }}>
          Run the multi-agent scholarship research pipeline to evaluate candidates and synthesize 
          a grounded SOP draft for your top recommendation.
        </p>
      </div>
    );
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(editableText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([editableText], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `SOP_${sop.program_name.replace(/\s+/g, '_')}.md`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const toggleCheck = (index: number) => {
    setCheckedItems((prev) => ({ ...prev, [index]: !prev[index] }));
  };

  const wordCount = editableText.split(/\s+/).filter(Boolean).length;

  return (
    <div style={{ maxWidth: '1080px', margin: '32px auto', padding: '0 16px' }}>
      
      {/* Title & Program Header */}
      <div style={{ marginBottom: '28px' }}>
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          padding: '4px 12px',
          borderRadius: '20px',
          background: 'rgba(99, 102, 241, 0.1)',
          border: '1px solid rgba(99, 102, 241, 0.3)',
          color: '#818cf8',
          fontSize: '0.8125rem',
          fontWeight: '600',
          marginBottom: '10px'
        }}>
          <Sparkles size={14} /> Stage 5: Application Strategy Agent (ASA)
        </div>
        <h2 style={{ fontSize: '1.75rem', fontWeight: '800', color: '#ffffff', letterSpacing: '-0.02em' }}>
          Statement of Purpose & Strategic Application Dossier
        </h2>
        <p style={{ color: '#94a3b8', fontSize: '0.9375rem', marginTop: '4px' }}>
          Synthesized for <strong style={{ color: '#ffffff' }}>{sop.program_name}</strong> at <strong style={{ color: '#818cf8' }}>{sop.institution}</strong>.
        </p>
      </div>

      {/* Grounding Transparency Disclaimer */}
      <div style={{
        padding: '14px 18px',
        borderRadius: '12px',
        background: 'rgba(99, 102, 241, 0.08)',
        border: '1px solid rgba(99, 102, 241, 0.25)',
        marginBottom: '28px',
        display: 'flex',
        alignItems: 'flex-start',
        gap: '12px'
      }}>
        <AlertCircle size={20} color="#818cf8" style={{ flexShrink: 0, marginTop: '2px' }} />
        <div style={{ fontSize: '0.8125rem', color: '#cbd5e1', lineHeight: '1.45' }}>
          <strong style={{ color: '#ffffff' }}>Evidence-Grounded Policy:</strong> This draft incorporates only verified 
          credentials and technical projects present in your profile. No grades, research accomplishments, or work 
          experiences have been fabricated. You must review and personalize this draft before submitting your official application.
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.8fr) minmax(0, 1.2fr)', gap: '28px', alignItems: 'start' }}>
        
        {/* Left Column: SOP Draft Editor */}
        <div className="card-container card-elevated" style={{ padding: '28px' }}>
          
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', borderBottom: '1px solid var(--border-dim)', paddingBottom: '14px' }}>
            <div>
              <h3 style={{ fontSize: '1.125rem', fontWeight: '800', color: '#ffffff' }}>
                Tailored SOP Draft
              </h3>
              <span style={{ fontSize: '0.75rem', color: '#94a3b8', fontFamily: 'var(--font-mono)' }}>
                {wordCount} words • Generated {new Date(sop.generated_at).toLocaleDateString()}
              </span>
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={handleCopy}
                className="btn btn-secondary"
                style={{ padding: '6px 12px', fontSize: '0.8125rem' }}
                title="Copy to clipboard"
                id="copy-sop-btn"
              >
                {copied ? <><Check size={14} color="#34d399" /> Copied!</> : <><Copy size={14} /> Copy</>}
              </button>

              <button
                onClick={handleDownload}
                className="btn btn-secondary"
                style={{ padding: '6px 12px', fontSize: '0.8125rem' }}
                title="Download as Markdown"
                id="download-sop-btn"
              >
                <Download size={14} /> Export
              </button>
            </div>
          </div>

          {/* Editable Text Area */}
          <textarea
            className="form-textarea"
            style={{
              width: '100%',
              minHeight: '440px',
              fontFamily: 'var(--font-sans)',
              fontSize: '0.9375rem',
              lineHeight: '1.7',
              padding: '16px',
              background: 'rgba(0, 0, 0, 0.4)',
              border: '1px solid var(--border-dim)',
              borderRadius: '10px',
              resize: 'vertical',
              color: '#f8fafc'
            }}
            value={editableText}
            onChange={(e) => setEditableText(e.target.value)}
          />

          <div style={{ marginTop: '12px', fontSize: '0.75rem', color: '#64748b', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span>* Edits are preserved in this view during your session.</span>
            <span>Draft ID: {sop.draft_id}</span>
          </div>

        </div>

        {/* Right Column: Application Checklist & Targeted Missing-Info Prompts */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Actionable Application Checklist */}
          <div className="card-container" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <h3 style={{ fontSize: '1rem', fontWeight: '800', color: '#ffffff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <CheckSquare size={18} color="#10b981" /> Application Checklist
              </h3>
              <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: '#34d399' }}>
                {Object.values(checkedItems).filter(Boolean).length} / {sop.suggested_revisions?.length || 0} Prepared
              </span>
            </div>

            {/* Preparation Guidance Notice */}
            <p style={{ fontSize: '0.75rem', color: '#94a3b8', lineHeight: '1.4', marginBottom: '16px' }}>
              <strong style={{ color: '#cbd5e1' }}>Preparation Guidance:</strong> These actionable tasks are synthesized from verified program requirements and your student profile. Checking an item marks your personal preparation progress; it does not submit your application to the university.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {sop.suggested_revisions?.map((item, idx) => {
                const isChecked = !!checkedItems[idx];
                let statusLabel = 'ACTION REQUIRED';
                let statusColor = '#fbbf24';
                let statusBg = 'rgba(245, 158, 11, 0.12)';
                let statusBorder = 'rgba(245, 158, 11, 0.3)';
                let cleanText = item;

                if (item.includes('[CONFIRMED')) {
                  statusLabel = 'CONFIRMED REQUIREMENT';
                  statusColor = '#34d399';
                  statusBg = 'rgba(16, 185, 129, 0.12)';
                  statusBorder = 'rgba(16, 185, 129, 0.3)';
                  cleanText = item.replace(/^\[CONFIRMED[^\]]*\]\s*/, '');
                } else if (item.includes('[USER ACTION')) {
                  statusLabel = 'USER ACTION REQUIRED';
                  statusColor = '#fbbf24';
                  statusBg = 'rgba(245, 158, 11, 0.12)';
                  statusBorder = 'rgba(245, 158, 11, 0.3)';
                  cleanText = item.replace(/^\[USER ACTION[^\]]*\]\s*/, '');
                } else if (item.includes('[NEEDS VERIFICATION') || item.includes('[UNCONFIRMED')) {
                  statusLabel = 'NEEDS VERIFICATION';
                  statusColor = '#818cf8';
                  statusBg = 'rgba(99, 102, 241, 0.12)';
                  statusBorder = 'rgba(99, 102, 241, 0.3)';
                  cleanText = item.replace(/^\[(?:NEEDS VERIFICATION|UNCONFIRMED)[^\]]*\]\s*/, '');
                }

                return (
                  <div
                    key={idx}
                    onClick={() => toggleCheck(idx)}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '12px',
                      padding: '12px 14px',
                      borderRadius: '8px',
                      background: isChecked 
                        ? 'rgba(16, 185, 129, 0.08)' 
                        : 'rgba(255, 255, 255, 0.02)',
                      border: isChecked 
                        ? '1px solid rgba(16, 185, 129, 0.3)' 
                        : '1px solid var(--border-dim)',
                      cursor: 'pointer',
                      fontSize: '0.8125rem',
                      lineHeight: '1.45',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <span style={{ color: isChecked ? '#34d399' : '#94a3b8', marginTop: '2px', flexShrink: 0 }}>
                      {isChecked ? <CheckSquare size={17} /> : <Square size={17} />}
                    </span>
                    <div style={{ flex: 1 }}>
                      <div style={{ marginBottom: '4px' }}>
                        <span style={{
                          display: 'inline-block',
                          fontSize: '0.65rem',
                          fontWeight: '700',
                          fontFamily: 'var(--font-mono)',
                          padding: '1px 6px',
                          borderRadius: '4px',
                          color: statusColor,
                          background: statusBg,
                          border: `1px solid ${statusBorder}`,
                          letterSpacing: '0.02em'
                        }}>
                          {statusLabel}
                        </span>
                      </div>
                      <span style={{
                        color: isChecked ? '#94a3b8' : '#e2e8f0',
                        textDecoration: isChecked ? 'line-through' : 'none'
                      }}>
                        {cleanText}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Missing Information Prompts */}
          <div className="card-container" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: '800', color: '#ffffff', marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <HelpCircle size={18} color="#f59e0b" /> Targeted Questions to Personalize
            </h3>
            <p style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '12px' }}>
              Answer these questions to add personal context to your SOP before submission:
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {sop.missing_info_prompts?.map((prompt, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '10px 14px',
                    borderRadius: '8px',
                    background: 'rgba(245, 158, 11, 0.06)',
                    border: '1px solid rgba(245, 158, 11, 0.2)',
                    fontSize: '0.8125rem',
                    color: '#e2e8f0'
                  }}
                >
                  <p style={{ fontWeight: '600', color: '#fbbf24', marginBottom: '2px', fontSize: '0.75rem' }}>
                    PROMPT #{idx + 1}
                  </p>
                  <p>{prompt}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Cited Profile Elements */}
          <div className="card-container" style={{ padding: '24px' }}>
            <h3 style={{ fontSize: '0.9375rem', fontWeight: '800', color: '#ffffff', marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <BookOpen size={16} color="#818cf8" /> Grounded In Profile Data
            </h3>
            <ul style={{ paddingLeft: '18px', fontSize: '0.75rem', color: '#cbd5e1', lineHeight: '1.6' }}>
              {sop.cited_profile_elements?.map((elem, idx) => (
                <li key={idx}>{elem}</li>
              ))}
            </ul>
          </div>

        </div>

      </div>

    </div>
  );
};
