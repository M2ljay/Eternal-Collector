/**
 * The plugin's icons: line icons in Core's style (24-unit grid, 1.8 stroke,
 * round joins, `currentColor`), the way the Core boards draw them. `size`
 * defaults to 1em, so an icon follows the font size it sits in.
 */

import type { CSSProperties, FC, ReactNode } from "react";

export interface IconProps {
  size?: number | string | undefined;
  color?: string | undefined;
  style?: CSSProperties | undefined;
  className?: string | undefined;
  role?: string | undefined;
  "aria-label"?: string | undefined;
}

function icon(body: ReactNode): FC<IconProps> {
  const Icon: FC<IconProps> = ({ size = "1em", color = "currentColor", role, ...rest }) => (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke={color}
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={rest["aria-label"] ? undefined : true}
      role={role}
      {...rest}
    >
      {body}
    </svg>
  );
  return Icon;
}

export const CogIcon = icon(
  <>
    <circle cx="12" cy="12" r="3.2" />
    <path d="M12 2.5V5.5M12 18.5V21.5M2.5 12H5.5M18.5 12H21.5M5.3 5.3L7.4 7.4M16.6 16.6L18.7 18.7M5.3 18.7L7.4 16.6M16.6 7.4L18.7 5.3" />
  </>,
);

export const ChipIcon = icon(
  <>
    <rect x="6" y="6" width="12" height="12" />
    <rect x="9.5" y="9.5" width="5" height="5" />
    <path d="M9 3V6M15 3V6M9 18V21M15 18V21M3 9H6M3 15H6M18 9H21M18 15H21" />
  </>,
);

export const WarningIcon = icon(<path d="M12 3L22 20H2ZM12 9.5V14M12 17V17.2" />);

export const ChevronDownIcon = icon(<path d="M6 9L12 15L18 9" />);

export const TrashIcon = icon(<path d="M4 7H20M9 7V4H15V7M6 7L7 21H17L18 7M10 11V17M14 11V17" />);

export const CrossCircleIcon = icon(
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M9 9L15 15M15 9L9 15" />
  </>,
);

export const CheckCircleIcon = icon(
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M8 12.5L11 15.5L16.5 9" />
  </>,
);

export const LayersIcon = icon(<path d="M12 3L21 8L12 13L3 8ZM3 12.5L12 17.5L21 12.5M3 17L12 22L21 17" />);

export const DiscIcon = icon(
  <>
    <circle cx="12" cy="12" r="9" />
    <circle cx="12" cy="12" r="2.5" />
  </>,
);

export const WindowsIcon = icon(
  <path d="M3 5.5L10.5 4.5V11.5H3ZM13 4.2L21 3V11.5H13ZM3 12.5H10.5V19.5L3 18.5ZM13 12.5H21V21L13 19.8Z" />,
);

export const PuzzleIcon = icon(
  <path d="M4 8H8A2.5 2.5 0 1 1 13 8H17V12A2.5 2.5 0 1 1 17 17V21H4V17A2.5 2.5 0 1 0 4 12Z" />,
);

export const GamepadIcon = icon(
  <>
    <path d="M7 8H17A4 4 0 0 1 21 12L20 17A2 2 0 0 1 16.5 18L15 16H9L7.5 18A2 2 0 0 1 4 17L3 12A4 4 0 0 1 7 8Z" />
    <path d="M7 12H10M8.5 10.5V13.5" />
  </>,
);

export const CartridgeIcon = icon(
  <>
    <path d="M6 3H18V21H16V19H8V21H6Z" />
    <rect x="9" y="6" width="6" height="6" />
  </>,
);
