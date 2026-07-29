import Nav from "@/components/Nav";

/**
 * The product pages. `/p/<id>` is deliberately outside this group — see `components/Nav`.
 */
export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Nav />
      {children}
    </>
  );
}
