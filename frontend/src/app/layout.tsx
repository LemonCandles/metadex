import type { Metadata } from "next";
import Link from "next/link";
import { HeroCatalogProvider } from "@/components/hero-catalog";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Metadex | Meta de Dota 2", template: "%s | Metadex" },
  description: "Picks, win rate, draft e itens de Dota 2 com período, amostra e contexto visíveis.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="pt-BR"><body><a className="skip-link" href="#main-content">Pular para o conteúdo</a><header className="site-header"><div className="header-inner"><Link className="brand" href="/" aria-label="Metadex — início"><span className="brand-mark" aria-hidden="true">M</span><span>META<span>DEX</span></span></Link><nav aria-label="Navegação principal"><Link href="/">Meta de heróis</Link><Link href="/recommendations">Draft e itens</Link></nav><span className="header-status">ESTATÍSTICAS DE DOTA 2</span></div></header><div id="main-content"><HeroCatalogProvider>{children}</HeroCatalogProvider></div><footer className="site-footer"><div><span className="brand-footer">METADEX</span><p>Um catálogo estatístico, não uma promessa de resultado.</p></div><div><Link href="/">Heróis</Link><Link href="/recommendations">Draft e itens</Link></div><small>Dados da publicação local · horário UTC</small></footer></body></html>;
}
