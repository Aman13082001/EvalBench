"use client";

import { useState } from "react";
import LoginDialog from "@/components/LoginDialog";

/* One way to sign in, everywhere: the dialog over the current page. The
   nav link, the homepage call-to-action and the example page's closing
   button all render this, so there is a single login UI rather than a
   dialog in one place and a page in another. /login stays a route only
   because the auth redirect needs somewhere to land. */
export default function SignIn({
  className,
  children,
}: {
  className: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={className} onClick={() => setOpen(true)}>
        {children}
      </button>
      <LoginDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}
