import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Metadex | Observatório do meta", template: "%s | Metadex" },
  description: "Escolhas, vitórias, tendências e recomendações de Dota 2 com período, amostra e contexto visíveis.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="pt-BR"><body><a className="skip-link" href="#main-content">Pular para o conteúdo</a><header className="site-header"><div className="header-inner"><Link className="brand" href="/" aria-label="Metadex — início"><span className="brand-mark" aria-hidden="true">M</span><span>META<span>DEX</span></span></Link><nav aria-label="Navegação principal"><Link href="/">Visão geral</Link><Link href="/recommendations">Recomendações</Link></nav><span className="header-status"><span className="live-dot" /> DADOS PUBLICADOS</span></div></header><div id="main-content">{children}</div><footer className="site-footer"><div><span className="brand-footer">METADEX</span><p>Um catálogo estatístico, não uma promessa de resultado.</p></div><div><Link href="/">Heróis</Link><Link href="/recommendations">Recomendações</Link></div><small>Dados da publicação local · horário UTC</small></footer></body></html>;
}
