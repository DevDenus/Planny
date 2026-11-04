import type { ReactNode } from "react";

import { Logo } from "../../ui";
import styles from "./AuthLayout.module.css";

function Ridges() {
  return (
    <svg
      className={styles.ridges}
      viewBox="0 0 1440 900"
      preserveAspectRatio="xMidYMax slice"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="ridge-far" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--ridge-far)" />
          <stop offset="0.7" stopColor="var(--ridge-near)" />
        </linearGradient>
        <linearGradient id="ridge-mid" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--ridge-mid)" />
          <stop offset="0.7" stopColor="var(--ridge-near)" />
        </linearGradient>
      </defs>
      <path
        fill="url(#ridge-far)"
        d="M0 640C120 600 170 590 250 618S380 650 470 612 640 560 760 604 940 668 1060 618 1230 558 1330 590 1420 626 1440 630V900H0Z"
      />
      <path
        fill="url(#ridge-mid)"
        d="M0 694C110 660 210 640 330 676S520 738 660 690 860 640 1000 682 1220 742 1340 700 1420 672 1440 668V900H0Z"
      />
      <path
        fill="var(--ridge-near)"
        d="M0 770C160 730 280 720 430 752S690 812 860 772 1130 716 1280 752 1400 790 1440 782V900H0Z"
      />
    </svg>
  );
}

/** A centred block on the backdrop, for states that come before a form or the app shell. */
export function FullScreen({ children }: { children: ReactNode }) {
  return (
    <div className={styles.backdrop}>
      <Ridges />
      <div className={styles.status}>{children}</div>
    </div>
  );
}

interface AuthLayoutProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}

export function AuthLayout({ title, subtitle, children, footer }: AuthLayoutProps) {
  return (
    <div className={styles.backdrop}>
      <Ridges />
      <main className={styles.panel}>
        <Logo size="lg" />
        <div className={styles.heading}>
          <h1 className={styles.title}>{title}</h1>
          {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
        </div>
        {children}
        {footer && <p className={styles.footer}>{footer}</p>}
      </main>
    </div>
  );
}
