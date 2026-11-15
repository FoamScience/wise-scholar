/** The mark: "ws" written in one pen stroke, with an amber dot like the tittle of an i. */
export default function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" role="img" aria-label="wise-scholar">
      <rect width="512" height="512" rx="112" fill="#0b5f5a" />
      <path
        d="M92 214c12 62 26 126 54 126 28 0 40-96 56-96s28 96 56 96 38-76 44-120c22-10 60-16 90 2-32-18-76-2-62 30 12 28 70 26 70 64 0 36-54 44-86 18"
        fill="none"
        stroke="#f4faf9"
        strokeWidth="32"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="414" cy="158" r="26" fill="#f0b35c" />
    </svg>
  )
}
