import React, { useState } from 'react';
import { 
  Upload, 
  FileText, 
  AlertCircle, 
  ArrowRight, 
  Sparkles, 
  Code2, 
  GraduationCap,
  CheckCircle2,
  RotateCcw
} from 'lucide-react';
import { createSession, extractProfilePreview } from '../api';
import type { DegreeLevel, SessionRecord } from '../types';

interface ProfileFormProps {
  onSessionCreated: (session: SessionRecord) => void;
  onResetSession?: () => void;
}

export const ProfileForm: React.FC<ProfileFormProps> = ({ onSessionCreated, onResetSession }) => {
  const [loading, setLoading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successNotice, setSuccessNotice] = useState<string | null>(null);

  // Core Mandatory Fields
  const [fieldOfStudy, setFieldOfStudy] = useState('Computer Science');
  const [targetDegree, setTargetDegree] = useState<DegreeLevel>('masters');
  const [preferredCountries, setPreferredCountries] = useState('Worldwide');

  // Document Upload State
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [transcriptFile, setTranscriptFile] = useState<File | null>(null);

  // Academic Grade & Scale Fields
  const [cgpa, setCgpa] = useState<string>('');
  const [cgpaScale, setCgpaScale] = useState<string>('10.0');

  // Extraction Provenance & Transparency Tracking
  const [extractionSource, setExtractionSource] = useState<string | null>(null);
  const [extractionEvidence, setExtractionEvidence] = useState<string | null>(null);
  const [isAmbiguous, setIsAmbiguous] = useState<boolean>(false);
  const [ambiguityReason, setAmbiguityReason] = useState<string | null>(null);

  // Applicant Profile Fields (empty by default to avoid fabricating credentials)
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [nationality, setNationality] = useState('');
  const [currentDegree, setCurrentDegree] = useState('');
  const [workExperience, setWorkExperience] = useState<string>('');
  const [ieltsScore, setIeltsScore] = useState<string>('');
  const [greScore, setGreScore] = useState<string>('');
  const [githubUrl, setGithubUrl] = useState('');
  const [skillsText, setSkillsText] = useState('');

  // Handle Document Selection with Automatic Preview Extraction
  const handleDocumentExtraction = async (file: File, type: 'resume' | 'transcript') => {
    setExtracting(true);
    setError(null);
    setSuccessNotice(null);

    const formData = new FormData();
    if (type === 'resume') {
      formData.append('resume_file', file);
      if (transcriptFile) formData.append('transcript_file', transcriptFile);
    } else {
      formData.append('transcript_file', file);
      if (resumeFile) formData.append('resume_file', resumeFile);
    }

    try {
      const preview = await extractProfilePreview(formData);
      
      // Populate fields from extracted preview if currently blank or updating
      if (preview.name && !name) setName(preview.name);
      if (preview.email && !email) setEmail(preview.email);
      if (preview.current_degree && !currentDegree) setCurrentDegree(preview.current_degree);
      
      if (preview.cgpa !== null && preview.cgpa !== undefined) {
        setCgpa(String(preview.cgpa));
        setCgpaScale(preview.cgpa_scale !== null && preview.cgpa_scale !== undefined ? String(preview.cgpa_scale) : '');
        setExtractionSource(preview.cgpa_source || `Extracted from ${file.name}`);
        setExtractionEvidence(preview.cgpa_evidence);
        setIsAmbiguous(preview.is_ambiguous);
        setAmbiguityReason(preview.ambiguity_reason);
      } else {
        setExtractionSource(null);
        setExtractionEvidence(null);
        setIsAmbiguous(false);
        setAmbiguityReason(null);
      }

      if (preview.ielts_score !== null && preview.ielts_score !== undefined && !ieltsScore) {
        setIeltsScore(String(preview.ielts_score));
      }
      if (preview.gre_score !== null && preview.gre_score !== undefined && !greScore) {
        setGreScore(String(preview.gre_score));
      }
      if (preview.work_experience_years !== null && preview.work_experience_years !== undefined && !workExperience) {
        setWorkExperience(String(preview.work_experience_years));
      }
      if (preview.skills && preview.skills.length > 0 && !skillsText) {
        setSkillsText(preview.skills.join(', '));
      }

      setSuccessNotice(`Parsed ${file.name} successfully. Academic credentials populated for your review.`);
    } catch (err: any) {
      setError(`Extraction warning: ${err?.message || 'Could not auto-extract fields from document.'} You can enter details manually below.`);
    } finally {
      setExtracting(false);
    }
  };

  const handleResumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (file.size > 10 * 1024 * 1024) {
        setError('Resume file exceeds maximum 10 MiB limit.');
        return;
      }
      setResumeFile(file);
      handleDocumentExtraction(file, 'resume');
    }
  };

  const handleTranscriptChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (file.size > 10 * 1024 * 1024) {
        setError('Transcript file exceeds maximum 10 MiB limit.');
        return;
      }
      setTranscriptFile(file);
      handleDocumentExtraction(file, 'transcript');
    }
  };

  // Reset form to blank fresh state
  const handleResetForm = () => {
    setResumeFile(null);
    setTranscriptFile(null);
    setName('');
    setEmail('');
    setNationality('');
    setCurrentDegree('');
    setCgpa('');
    setCgpaScale('10.0');
    setExtractionSource(null);
    setExtractionEvidence(null);
    setIsAmbiguous(false);
    setAmbiguityReason(null);
    setWorkExperience('');
    setIeltsScore('');
    setGreScore('');
    setGithubUrl('');
    setSkillsText('');
    setPreferredCountries('Worldwide');
    setError(null);
    setSuccessNotice(null);
    if (onResetSession) {
      onResetSession();
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!fieldOfStudy.trim()) {
      setError('Field of Study is required.');
      return;
    }

    // Validate CGPA & Scale relationship if both are specified
    const parsedCgpa = cgpa.trim() ? parseFloat(cgpa) : undefined;
    const parsedScale = cgpaScale.trim() ? parseFloat(cgpaScale) : undefined;

    if (parsedCgpa !== undefined && parsedCgpa < 0) {
      setError('CGPA cannot be negative.');
      return;
    }

    if (parsedCgpa !== undefined && parsedScale !== undefined) {
      if (parsedScale <= 0) {
        setError('Grading scale maximum must be a positive number.');
        return;
      }
      if (parsedCgpa > parsedScale) {
        setError(`Entered grade (${parsedCgpa}) cannot exceed the specified maximum scale (${parsedScale}).`);
        return;
      }
    }

    setLoading(true);

    try {
      const formData = new FormData();
      formData.append('field_of_study', fieldOfStudy.trim());
      formData.append('target_degree', targetDegree);
      if (preferredCountries.trim()) {
        formData.append('preferred_countries', preferredCountries.trim());
      }
      if (name.trim()) formData.append('name', name.trim());
      if (email.trim()) formData.append('email', email.trim());
      if (nationality.trim()) formData.append('nationality', nationality.trim());
      if (currentDegree.trim()) formData.append('current_degree', currentDegree.trim());
      
      // Explicit CGPA and Scale
      if (cgpa.trim()) {
        formData.append('cgpa', cgpa.trim());
      } else {
        formData.append('cgpa', '');
      }

      if (cgpaScale.trim()) {
        formData.append('cgpa_scale', cgpaScale.trim());
      } else {
        formData.append('cgpa_scale', 'unknown');
      }

      if (workExperience.trim()) formData.append('work_experience_years', workExperience.trim());
      if (ieltsScore.trim()) formData.append('ielts_score', ieltsScore.trim());
      if (greScore.trim()) formData.append('gre_score', greScore.trim());
      if (githubUrl.trim()) formData.append('github_url', githubUrl.trim());
      if (skillsText.trim()) formData.append('skills_text', skillsText.trim());

      if (resumeFile) formData.append('resume_file', resumeFile);
      if (transcriptFile) formData.append('transcript_file', transcriptFile);

      const sessionResult = await createSession(formData);
      onSessionCreated(sessionResult);
    } catch (err: any) {
      setError(err?.message || 'Failed to create student research session. Please check your inputs.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: '960px', margin: '32px auto', padding: '0 16px' }}>
      
      {/* Title & Introduction */}
      <div style={{ textAlign: 'center', marginBottom: '28px' }}>
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
          marginBottom: '12px'
        }}>
          <Sparkles size={14} /> Step 1: Student Profile & Academic Credentials
        </div>
        <h1 style={{ fontSize: '2rem', fontWeight: '800', letterSpacing: '-0.02em', color: '#ffffff' }}>
          Student Profile Ingestion
        </h1>
        <p style={{ color: '#94a3b8', fontSize: '0.9375rem', marginTop: '8px', maxWidth: '680px', margin: '8px auto 0' }}>
          Provide your academic credentials and destination preferences. You can enter grades directly or upload a resume for automatic extraction with full manual review.
        </p>
      </div>

      {/* Main Form Card */}
      <form onSubmit={handleSubmit} className="card-container card-elevated" style={{ padding: '32px' }}>
        
        {/* Card Header with Fresh Session Action */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', borderBottom: '1px solid var(--border-dim)', paddingBottom: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <FileText size={20} color="#6366f1" />
            <h2 style={{ fontSize: '1.125rem', fontWeight: '700', color: '#ffffff', margin: 0 }}>
              Profile & Grading Details
            </h2>
          </div>
          <button
            type="button"
            onClick={handleResetForm}
            className="btn btn-secondary"
            style={{ fontSize: '0.75rem', padding: '5px 12px', display: 'flex', alignItems: 'center', gap: '6px' }}
            title="Clear all fields and start a fresh profile"
          >
            <RotateCcw size={14} /> Start Fresh Session
          </button>
        </div>

        {/* Global Error Banner */}
        {error && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: '12px 16px',
            borderRadius: '10px',
            background: 'rgba(244, 63, 94, 0.12)',
            border: '1px solid rgba(244, 63, 94, 0.3)',
            color: '#fb7185',
            fontSize: '0.875rem',
            marginBottom: '24px'
          }}>
            <AlertCircle size={18} style={{ flexShrink: 0 }} />
            <span>{error}</span>
          </div>
        )}

        {/* Success / Ingestion Notice */}
        {successNotice && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            padding: '12px 16px',
            borderRadius: '10px',
            background: 'rgba(16, 185, 129, 0.12)',
            border: '1px solid rgba(16, 185, 129, 0.3)',
            color: '#34d399',
            fontSize: '0.875rem',
            marginBottom: '24px'
          }}>
            <CheckCircle2 size={18} style={{ flexShrink: 0 }} />
            <span>{successNotice}</span>
          </div>
        )}

        {/* SECTION A: Target Program & Destination Constraints */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px', marginBottom: '24px' }}>
          <div>
            <label className="form-label" htmlFor="field_of_study">
              Target Field of Study *
            </label>
            <input
              id="field_of_study"
              type="text"
              required
              className="form-input"
              value={fieldOfStudy}
              onChange={(e) => setFieldOfStudy(e.target.value)}
              placeholder="e.g. Computer Science, Artificial Intelligence"
            />
            <span style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '4px', display: 'block' }}>
              Used to match faculty departments and degree offerings.
            </span>
          </div>

          <div>
            <label className="form-label" htmlFor="target_degree">
              Target Degree Level *
            </label>
            <select
              id="target_degree"
              className="form-select"
              value={targetDegree}
              onChange={(e) => setTargetDegree(e.target.value as DegreeLevel)}
            >
              <option value="masters">Master's Degree (MSc / MA / MPhil)</option>
              <option value="phd">Doctoral Degree (PhD / DPhil)</option>
              <option value="undergraduate">Undergraduate (BSc / BA)</option>
              <option value="postdoc">Postdoctoral Fellowship</option>
            </select>
            <span style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '4px', display: 'block' }}>
              Hard constraint enforced during admission & scholarship checks.
            </span>
          </div>
        </div>

        {/* Preferred Host Destinations */}
        <div style={{ marginBottom: '28px' }}>
          <label className="form-label" htmlFor="preferred_countries">
            Preferred Host Destinations (Country Filter)
          </label>
          <input
            id="preferred_countries"
            type="text"
            className="form-input"
            value={preferredCountries}
            onChange={(e) => setPreferredCountries(e.target.value)}
            placeholder="e.g. Canada, Germany, United Kingdom"
          />
          <span style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '4px', display: 'block' }}>
            Opportunities are strictly filtered to matching destination countries.
          </span>
          <div style={{ display: 'flex', gap: '8px', marginTop: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.75rem', color: '#94a3b8', alignSelf: 'center' }}>Presets:</span>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '3px 10px', background: preferredCountries === 'Worldwide' ? 'rgba(99, 102, 241, 0.25)' : undefined }}
              onClick={() => setPreferredCountries('Worldwide')}
            >
              Worldwide / Any
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '3px 10px' }}
              onClick={() => setPreferredCountries('New Zealand')}
            >
              New Zealand
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '3px 10px' }}
              onClick={() => setPreferredCountries('Australia')}
            >
              Australia
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '3px 10px' }}
              onClick={() => setPreferredCountries('Canada')}
            >
              Canada
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '3px 10px' }}
              onClick={() => setPreferredCountries('Canada, New Zealand, Australia')}
            >
              Canada + NZ + Australia
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '3px 10px' }}
              onClick={() => setPreferredCountries('United States, Canada')}
            >
              USA & Canada
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '3px 10px' }}
              onClick={() => setPreferredCountries('United Kingdom, Ireland')}
            >
              UK & Ireland
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '3px 10px' }}
              onClick={() => setPreferredCountries('Germany, France, Switzerland')}
            >
              Europe (Germany, France, Swiss)
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '3px 10px' }}
              onClick={() => setPreferredCountries('Japan, Singapore')}
            >
              Asia (Japan, Singapore)
            </button>
          </div>
        </div>

        {/* SECTION B: ALWAYS-VISIBLE ACADEMIC GRADE & SCALE (ISSUE 2 FIX) */}
        <div style={{
          background: 'rgba(99, 102, 241, 0.04)',
          border: '1px solid rgba(99, 102, 241, 0.25)',
          borderRadius: '12px',
          padding: '20px',
          marginBottom: '28px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', flexWrap: 'wrap', gap: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <GraduationCap size={20} color="#818cf8" />
              <h3 style={{ fontSize: '1rem', fontWeight: '700', color: '#ffffff', margin: 0 }}>
                Academic Grade & Grading Scale (Visible & Editable)
              </h3>
            </div>

            {/* Provenance Badge */}
            {extractionSource ? (
              <span style={{
                fontSize: '0.75rem',
                padding: '3px 10px',
                borderRadius: '12px',
                background: 'rgba(16, 185, 129, 0.15)',
                color: '#34d399',
                border: '1px solid rgba(16, 185, 129, 0.3)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px'
              }}>
                <CheckCircle2 size={12} /> {extractionSource}
              </span>
            ) : (
              <span style={{
                fontSize: '0.75rem',
                padding: '3px 10px',
                borderRadius: '12px',
                background: 'rgba(255, 255, 255, 0.05)',
                color: '#94a3b8',
                border: '1px solid var(--border-mid)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px'
              }}>
                ✍️ Entered manually
              </span>
            )}
          </div>

          {/* Ambiguity Alert Callout */}
          {isAmbiguous && ambiguityReason && (
            <div style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: '10px',
              padding: '12px 14px',
              borderRadius: '8px',
              background: 'rgba(245, 158, 11, 0.12)',
              border: '1px solid rgba(245, 158, 11, 0.35)',
              color: '#fbbf24',
              fontSize: '0.8125rem',
              marginBottom: '16px',
              lineHeight: 1.4
            }}>
              <AlertCircle size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
              <div>
                <strong>Grade Ambiguity Warning:</strong> {ambiguityReason}
                <div style={{ marginTop: '4px', fontSize: '0.75rem', color: '#fef3c7' }}>
                  Please confirm your university undergraduate CGPA and select the matching grading scale below.
                </div>
              </div>
            </div>
          )}

          {/* Extracted Evidence Snippet */}
          {extractionEvidence && (
            <div style={{
              fontSize: '0.75rem',
              color: '#94a3b8',
              marginBottom: '14px',
              padding: '6px 12px',
              borderRadius: '6px',
              background: 'rgba(0, 0, 0, 0.25)',
              border: '1px solid var(--border-dim)',
              fontFamily: 'var(--font-mono)'
            }}>
              Matched Text: "{extractionEvidence}"
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '16px', marginBottom: '14px' }}>
            {/* Grade Value Input */}
            <div>
              <label className="form-label" htmlFor="student_cgpa">
                Academic Grade / CGPA Value
              </label>
              <input
                id="student_cgpa"
                type="number"
                step="0.01"
                min="0"
                className="form-input"
                value={cgpa}
                onChange={(e) => {
                  setCgpa(e.target.value);
                  if (extractionSource && !extractionSource.includes('manual')) {
                    setExtractionSource('Edited manually after document extraction');
                    setIsAmbiguous(false);
                  }
                }}
                placeholder="e.g. 7.6, 3.85, 76.0"
              />
              <span style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '4px', display: 'block' }}>
                Your actual numerical grade without automatic multiplication.
              </span>
            </div>

            {/* Grading Scale Selector */}
            <div>
              <label className="form-label" htmlFor="student_cgpa_scale">
                Grading Scale System
              </label>
              <div style={{ display: 'flex', gap: '8px' }}>
                <select
                  id="student_cgpa_scale"
                  className="form-select"
                  value={
                    cgpaScale === '10.0' || cgpaScale === '10' ? '10.0' :
                    cgpaScale === '4.0' || cgpaScale === '4' ? '4.0' :
                    cgpaScale === '100.0' || cgpaScale === '100' ? '100.0' :
                    cgpaScale === '' ? 'unknown' : 'custom'
                  }
                  onChange={(e) => {
                    const val = e.target.value;
                    if (val === '10.0') setCgpaScale('10.0');
                    else if (val === '4.0') setCgpaScale('4.0');
                    else if (val === '100.0') setCgpaScale('100.0');
                    else if (val === 'unknown') setCgpaScale('');
                    else if (val === 'custom') setCgpaScale('5.0');
                    
                    if (extractionSource && !extractionSource.includes('manual')) {
                      setExtractionSource('Edited manually after document extraction');
                      setIsAmbiguous(false);
                    }
                  }}
                  style={{ flex: 1 }}
                >
                  <option value="10.0">10.0 Scale (e.g. India / Europe)</option>
                  <option value="4.0">4.0 Scale (e.g. US / Canada)</option>
                  <option value="100.0">100.0 (Percentage %)</option>
                  <option value="custom">Custom Scale...</option>
                  <option value="unknown">Unknown / Unspecified Scale</option>
                </select>

                {/* Custom Scale Input */}
                {!(cgpaScale === '10.0' || cgpaScale === '4.0' || cgpaScale === '100.0' || cgpaScale === '') && (
                  <input
                    id="student_custom_scale"
                    type="number"
                    step="0.1"
                    min="1"
                    className="form-input"
                    style={{ width: '84px' }}
                    value={cgpaScale}
                    onChange={(e) => setCgpaScale(e.target.value)}
                    placeholder="Max"
                    title="Enter custom scale maximum"
                  />
                )}
              </div>
              <span style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '4px', display: 'block' }}>
                {cgpaScale === '100.0'
                  ? 'Grade treated as academic percentage (%) out of 100.'
                  : cgpaScale
                  ? `Grade explicitly formatted as ${cgpa || '0'} / ${cgpaScale}.`
                  : 'Scale unknown: direct scale comparisons against 4.0 will be marked UNKNOWN.'}
              </span>
            </div>
          </div>

          {/* Quick Grade Presets */}
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center', marginTop: '8px' }}>
            <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Quick Presets:</span>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '2px 8px' }}
              onClick={() => {
                setCgpa('7.6');
                setCgpaScale('10.0');
                setExtractionSource('Entered manually (7.6 / 10.0)');
                setIsAmbiguous(false);
              }}
            >
              7.6 / 10.0 CGPA
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '2px 8px' }}
              onClick={() => {
                setCgpa('76.0');
                setCgpaScale('100.0');
                setExtractionSource('Entered manually (76% percentage)');
                setIsAmbiguous(false);
              }}
            >
              76% (Percentage)
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '2px 8px' }}
              onClick={() => {
                setCgpa('3.85');
                setCgpaScale('4.0');
                setExtractionSource('Entered manually (3.85 / 4.0)');
                setIsAmbiguous(false);
              }}
            >
              3.85 / 4.0 CGPA
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '2px 8px' }}
              onClick={() => {
                setCgpa('7.6');
                setCgpaScale('');
                setExtractionSource('Entered manually (Scale Unknown)');
                setIsAmbiguous(false);
              }}
            >
              7.6 (Scale Unknown)
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: '0.7rem', padding: '2px 8px', color: '#94a3b8' }}
              onClick={() => {
                setCgpa('');
                setCgpaScale('10.0');
                setExtractionSource(null);
                setExtractionEvidence(null);
                setIsAmbiguous(false);
              }}
            >
              Clear Grade
            </button>
          </div>
        </div>

        {/* SECTION C: DOCUMENT UPLOAD & EXTRACTION ZONE */}
        <div style={{ borderTop: '1px solid var(--border-dim)', paddingTop: '20px', marginBottom: '28px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: '700', color: '#e2e8f0', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Upload size={18} color="#6366f1" /> Upload Documents for Auto-Extraction (Optional)
            </h3>
            {extracting && (
              <span style={{ fontSize: '0.75rem', color: '#818cf8', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Sparkles size={14} className="spin" /> Deterministic SPA Parsing...
              </span>
            )}
          </div>
          
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px' }}>
            {/* Resume File */}
            <div style={{
              border: resumeFile ? '2px solid #10b981' : '2px dashed var(--border-mid)',
              borderRadius: '12px',
              padding: '20px 16px',
              textAlign: 'center',
              background: resumeFile ? 'rgba(16, 185, 129, 0.05)' : 'rgba(255, 255, 255, 0.02)',
              position: 'relative'
            }}>
              <FileText size={28} color={resumeFile ? '#10b981' : '#818cf8'} style={{ margin: '0 auto 8px' }} />
              <p style={{ fontSize: '0.875rem', fontWeight: '600', color: '#ffffff' }}>
                {resumeFile ? resumeFile.name : 'Upload Resume / CV (PDF or DOCX)'}
              </p>
              <p style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '4px' }}>
                {resumeFile ? 'Auto-extracted fields are populated above for review' : 'Extracts name, academic background, test scores & skills'}
              </p>
              <input
                type="file"
                id="resume_file"
                accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={handleResumeChange}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: '100%',
                  opacity: 0,
                  cursor: 'pointer'
                }}
              />
            </div>

            {/* Transcript File */}
            <div style={{
              border: transcriptFile ? '2px solid #10b981' : '2px dashed var(--border-mid)',
              borderRadius: '12px',
              padding: '20px 16px',
              textAlign: 'center',
              background: transcriptFile ? 'rgba(16, 185, 129, 0.05)' : 'rgba(255, 255, 255, 0.02)',
              position: 'relative'
            }}>
              <GraduationCap size={28} color={transcriptFile ? '#10b981' : '#94a3b8'} style={{ margin: '0 auto 8px' }} />
              <p style={{ fontSize: '0.875rem', fontWeight: '600', color: '#ffffff' }}>
                {transcriptFile ? transcriptFile.name : 'Upload Academic Transcript (Optional)'}
              </p>
              <p style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '4px' }}>
                {transcriptFile ? 'Transcript attached' : 'Validates courses, official grading scale & cumulative marks'}
              </p>
              <input
                type="file"
                id="transcript_file"
                accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={handleTranscriptChange}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: '100%',
                  opacity: 0,
                  cursor: 'pointer'
                }}
              />
            </div>
          </div>
        </div>

        {/* SECTION D: ADDITIONAL APPLICANT DETAILS */}
        <div style={{ borderTop: '1px solid var(--border-dim)', paddingTop: '20px', marginBottom: '28px' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: '700', color: '#e2e8f0', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Sparkles size={18} color="#6366f1" /> Additional Applicant Metadata (Optional)
          </h3>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px', marginBottom: '16px' }}>
            <div>
              <label className="form-label" htmlFor="student_name">Applicant Full Name</label>
              <input
                id="student_name"
                type="text"
                className="form-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Uday Pratap Chauhan"
              />
            </div>

            <div>
              <label className="form-label" htmlFor="student_email">Email Address</label>
              <input
                id="student_email"
                type="email"
                className="form-input"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="e.g. student@university.edu"
              />
            </div>

            <div>
              <label className="form-label" htmlFor="student_nationality">Nationality (Citizenship)</label>
              <input
                id="student_nationality"
                type="text"
                className="form-input"
                value={nationality}
                onChange={(e) => setNationality(e.target.value)}
                placeholder="e.g. India, Canada, Germany"
              />
            </div>

            <div>
              <label className="form-label" htmlFor="current_degree">Current Degree Title</label>
              <input
                id="current_degree"
                type="text"
                className="form-input"
                value={currentDegree}
                onChange={(e) => setCurrentDegree(e.target.value)}
                placeholder="e.g. BTech in Computer Science"
              />
            </div>

            <div>
              <label className="form-label" htmlFor="ielts_score">IELTS Overall Band</label>
              <input
                id="ielts_score"
                type="number"
                step="0.5"
                min="0"
                max="9"
                className="form-input"
                value={ieltsScore}
                onChange={(e) => setIeltsScore(e.target.value)}
                placeholder="e.g. 7.5 (leave blank if not taken)"
              />
            </div>

            <div>
              <label className="form-label" htmlFor="gre_score">GRE Total Score</label>
              <input
                id="gre_score"
                type="number"
                min="260"
                max="340"
                className="form-input"
                value={greScore}
                onChange={(e) => setGreScore(e.target.value)}
                placeholder="e.g. 320"
              />
            </div>

            <div>
              <label className="form-label" htmlFor="work_exp">Work Experience (Years)</label>
              <input
                id="work_exp"
                type="number"
                step="0.5"
                min="0"
                className="form-input"
                value={workExperience}
                onChange={(e) => setWorkExperience(e.target.value)}
                placeholder="e.g. 1.5"
              />
            </div>

            <div>
              <label className="form-label" htmlFor="github_url">Public GitHub Profile</label>
              <div style={{ position: 'relative' }}>
                <Code2 size={16} style={{ position: 'absolute', left: '12px', top: '12px', color: '#94a3b8' }} />
                <input
                  id="github_url"
                  type="url"
                  className="form-input"
                  style={{ paddingLeft: '38px' }}
                  value={githubUrl}
                  onChange={(e) => setGithubUrl(e.target.value)}
                  placeholder="https://github.com/username"
                />
              </div>
            </div>
          </div>

          <div>
            <label className="form-label" htmlFor="skills_text">Key Skills & Technical Competencies</label>
            <input
              id="skills_text"
              type="text"
              className="form-input"
              value={skillsText}
              onChange={(e) => setSkillsText(e.target.value)}
              placeholder="Comma-separated: Python, Machine Learning, PyTorch, Distributed Systems"
            />
          </div>
        </div>

        {/* Submit & Ingest Action */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '16px', flexWrap: 'wrap', gap: '12px' }}>
          <div style={{ fontSize: '0.8125rem', color: '#94a3b8' }}>
            {cgpa ? (
              <span>
                Configured Grade: <strong style={{ color: '#ffffff' }}>{cgpa}</strong>
                {cgpaScale === '100.0' ? '%' : cgpaScale ? ` / ${cgpaScale}` : ' (Scale Unknown)'}
              </span>
            ) : (
              <span>No grade specified (will evaluate without minimum GPA constraint)</span>
            )}
          </div>

          <button
            type="submit"
            disabled={loading || extracting}
            className="btn btn-primary"
            id="submit-profile-btn"
            style={{ minWidth: '240px', padding: '12px 24px', fontSize: '0.9375rem' }}
          >
            {loading ? (
              <>Creating Session & Ingesting...</>
            ) : (
              <>
                Confirm Profile & Discover Scholarships <ArrowRight size={18} />
              </>
            )}
          </button>
        </div>

      </form>

    </div>
  );
};
