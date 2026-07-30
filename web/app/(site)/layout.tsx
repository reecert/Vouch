import Footer from "@/components/Footer";
import Nav from "@/components/Nav";

/**
 * The product pages. `/p/<id>` is deliberately outside this group — see `components/Nav`.
 */
export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <Nav />
      <div className="flex-1">{children}</div>
      <Footer />
    </div>
  );
}
