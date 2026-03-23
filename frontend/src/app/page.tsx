import Link from "next/link";

const modules = [
  {
    title: "Legal Library",
    description:
      "Browse Romanian laws with full version history. Import, track changes, and cite precisely.",
    href: "/laws",
    status: "Active",
  },
  {
    title: "Legal Assistant",
    description:
      "Ask legal questions in Romanian or English. Get AI-powered answers with precise citations.",
    href: "/assistant",
    status: "Coming Soon",
  },
  {
    title: "Contract Review",
    description:
      "Upload contracts for AI-powered clause analysis, risk assessment, and legal compliance checks.",
    href: "/contracts",
    status: "Coming Soon",
  },
];

export default function Home() {
  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-2 text-gray-600">
          Legal & Compliance AI
        </p>
      </div>
      <div className="grid gap-6 md:grid-cols-3">
        {modules.map((mod) => (
          <Link
            key={mod.href}
            href={mod.href}
            className="block rounded-lg border border-gray-200 bg-white p-6 shadow-sm hover:shadow-md transition-shadow"
          >
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold text-gray-900">
                {mod.title}
              </h2>
              <span
                className={`text-xs font-medium px-2 py-1 rounded-full ${
                  mod.status === "Active"
                    ? "bg-green-100 text-green-700"
                    : "bg-gray-100 text-gray-500"
                }`}
              >
                {mod.status}
              </span>
            </div>
            <p className="text-sm text-gray-600">{mod.description}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
