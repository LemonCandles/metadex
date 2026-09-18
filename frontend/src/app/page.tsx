const principles = [
  "Dados brutos preservados",
  "Amostras sempre visíveis",
  "Coleta fora das requisições",
];

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16 sm:px-10">
      <p className="mb-4 text-sm font-semibold tracking-[0.22em] text-amber-400 uppercase">
        Estrutura inicial pronta
      </p>
      <h1 className="max-w-3xl text-5xl font-black tracking-tight sm:text-7xl">
        Metadex
      </h1>
      <p className="mt-6 max-w-2xl text-lg leading-8 text-zinc-400 sm:text-xl">
        Uma base auditável para acompanhar escolhas, vitórias e tendências do
        meta de Dota 2.
      </p>

      <section
        aria-labelledby="principios"
        className="mt-12 rounded-2xl border border-zinc-700 bg-zinc-900/80 p-6 shadow-2xl shadow-black/30"
      >
        <h2 id="principios" className="text-lg font-bold">
          Princípios do MVP
        </h2>
        <ul className="mt-5 grid gap-3 sm:grid-cols-3">
          {principles.map((principle) => (
            <li
              key={principle}
              className="rounded-xl border border-zinc-800 bg-zinc-950 p-4 text-sm text-zinc-300"
            >
              {principle}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
