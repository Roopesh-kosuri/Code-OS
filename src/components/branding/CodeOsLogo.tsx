type CodeOsLogoProps = {
  imageClassName?: string;
  className?: string;
  priority?: boolean;
};

export function CodeOsLogo({ imageClassName = "", className = "", priority = false }: CodeOsLogoProps) {
  return (
    <span className={`inline-flex items-center justify-center rounded-md bg-white/95 shadow-sm ring-1 ring-black/10 ${className}`}>
      <img
        src="/codeos-logo.png"
        alt="CODE OS"
        className={`select-none object-contain ${imageClassName}`}
        draggable={false}
        loading={priority ? "eager" : "lazy"}
      />
    </span>
  );
}
