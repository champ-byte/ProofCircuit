export function BrandMark({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 44 44" fill="none" aria-hidden="true" focusable="false">
      <rect width="44" height="44" rx="13" fill="#145B91" />
      <path d="M14 10.5h12l5 5V32a2 2 0 0 1-2 2H14a2 2 0 0 1-2-2V12.5a2 2 0 0 1 2-2Z" fill="white" />
      <path d="M26 10.5V16h5" fill="#CDEFF2" />
      <path d="M17 21h10M17 25h5" stroke="#9CB8CA" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="27" cy="27" r="7.5" fill="#14A59A" stroke="white" strokeWidth="2" />
      <path d="m23.8 27 2.1 2.1 4.3-4.5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
