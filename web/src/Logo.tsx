/** The mark: an open book whose pages form a W, with a spark above the spine. */
export default function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="wise-scholar">
      <rect width="32" height="32" rx="7" fill="#0b5f5a" />
      <path
        d="M6 11c3.5-1.2 7-1 10 1.4 3-2.4 6.5-2.6 10-1.4v12.2c-3.5-1.2-7-1-10 1.4-3-2.4-6.5-2.6-10-1.4z"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path d="M16 12.4v12.2" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" />
      <path d="M9.5 16.5l2.4 3.6 2.1-3.6M18 16.5l2.4 3.6 2.1-3.6" fill="none" stroke="#ffffff" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16" cy="6.5" r="1.8" fill="#f0b35c" />
    </svg>
  )
}
