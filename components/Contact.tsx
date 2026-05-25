'use client';
/**
 * components/Contact.tsx
 * --------------------------------------------------------------
 * Contact section with a form (Name, Email, Reason, Message).
 *
 * Submission flow:
 *   - If NEXT_PUBLIC_FORMSPREE_ENDPOINT is set, the form POSTs there.
 *   - Otherwise it just shows the success state (demo mode).
 *   - Either way it fires the "contact_form_submit" tracked event.
 *
 * PRIVACY NOTE: The visitor's name/email here are submitted *by them*,
 * voluntarily. We do not capture identity automatically anywhere else.
 */
import { useState } from 'react';
import { trackEvent } from '@/lib/analytics';

const REASONS = [
  'Internship',
  'Job Opportunity',
  'Research',
  'Collaboration',
  'Other',
];

export default function Contact() {
  const [status, setStatus] = useState<'idle' | 'sending' | 'success' | 'error'>(
    'idle'
  );
  const [form, setForm] = useState({
    name: '',
    email: '',
    reason: REASONS[0],
    message: '',
  });

  const endpoint = process.env.NEXT_PUBLIC_FORMSPREE_ENDPOINT;

  function update(field: string, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit() {
    // Minimal validation.
    if (!form.name || !form.email || !form.message) {
      setStatus('error');
      return;
    }

    setStatus('sending');

    // Always track the submit attempt.
    trackEvent('contact_form_submit', 'form', form.reason);

    // If Formspree is configured, actually send the message.
    if (endpoint && !endpoint.includes('your-form-id')) {
      try {
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { Accept: 'application/json' },
          body: JSON.stringify(form),
        });
        if (!res.ok) throw new Error('send failed');
        setStatus('success');
        setForm({ name: '', email: '', reason: REASONS[0], message: '' });
        return;
      } catch {
        setStatus('error');
        return;
      }
    }

    // Demo mode (no Formspree yet) — just show success.
    setStatus('success');
    setForm({ name: '', email: '', reason: REASONS[0], message: '' });
  }

  return (
    <section
      id="contact"
      className="py-24 border-t border-steel/40 bg-coal/30"
    >
      <div className="max-w-3xl mx-auto px-6">
        <p className="section-kicker">06 / Contact</p>
        <h2 className="mt-3 font-display font-bold text-3xl sm:text-4xl">
          Let&apos;s talk
        </h2>
        <p className="mt-3 text-ash">
          Reach out about internships, roles, research, or collaboration.
        </p>

        {/* Success state */}
        {status === 'success' ? (
          <div className="mt-10 bg-coal border border-gold/50 rounded-xl p-8 text-center">
            <div className="text-3xl mb-2">✅</div>
            <h3 className="font-display font-semibold text-gold text-lg">
              Message sent!
            </h3>
            <p className="text-ash text-sm mt-2">
              Thanks for reaching out — I&apos;ll get back to you soon.
            </p>
            <button
              onClick={() => setStatus('idle')}
              className="mt-5 text-sm text-gold hover:underline"
            >
              Send another message
            </button>
          </div>
        ) : (
          <div className="mt-10 bg-coal border border-steel/60 rounded-xl p-6 sm:p-8 space-y-5">
            {/* Name */}
            <div>
              <label className="block text-sm text-ash mb-1.5">Name</label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => update('name', e.target.value)}
                className="w-full px-3 py-2.5 rounded-lg bg-slate border border-steel text-chalk text-sm focus:outline-none focus:border-gold transition-colors"
                placeholder="Your name"
              />
            </div>

            {/* Email */}
            <div>
              <label className="block text-sm text-ash mb-1.5">Email</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => update('email', e.target.value)}
                className="w-full px-3 py-2.5 rounded-lg bg-slate border border-steel text-chalk text-sm focus:outline-none focus:border-gold transition-colors"
                placeholder="you@example.com"
              />
            </div>

            {/* Reason */}
            <div>
              <label className="block text-sm text-ash mb-1.5">
                Reason for Contact
              </label>
              <select
                value={form.reason}
                onChange={(e) => update('reason', e.target.value)}
                className="w-full px-3 py-2.5 rounded-lg bg-slate border border-steel text-chalk text-sm focus:outline-none focus:border-gold transition-colors"
              >
                {REASONS.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>

            {/* Message */}
            <div>
              <label className="block text-sm text-ash mb-1.5">Message</label>
              <textarea
                rows={5}
                value={form.message}
                onChange={(e) => update('message', e.target.value)}
                className="w-full px-3 py-2.5 rounded-lg bg-slate border border-steel text-chalk text-sm focus:outline-none focus:border-gold transition-colors resize-none"
                placeholder="Tell me a bit about what you have in mind..."
              />
            </div>

            {status === 'error' && (
              <p className="text-sm text-red-400">
                Please fill in your name, email, and message.
              </p>
            )}

            <button
              onClick={handleSubmit}
              disabled={status === 'sending'}
              className="w-full px-5 py-3 rounded-lg bg-gold text-ink font-semibold hover:bg-goldDark transition-colors disabled:opacity-60"
            >
              {status === 'sending' ? 'Sending...' : 'Send Message'}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
