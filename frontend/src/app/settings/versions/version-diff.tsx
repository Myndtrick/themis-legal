"use client";

export function VersionDiff({
  promptId,
  versionA,
  versionB,
  textA,
  textB,
}: {
  promptId: string;
  versionA: number;
  versionB: number;
  textA: string;
  textB: string;
}) {
  const linesA = textA.split("\n");
  const linesB = textB.split("\n");
  const maxLines = Math.max(linesA.length, linesB.length);

  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-900 mb-3">
        {promptId} — v{versionA} vs v{versionB}
      </h3>

      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden max-h-[60vh] overflow-y-auto">
        <pre className="text-xs font-mono p-0">
          {Array.from({ length: maxLines }, (_, i) => {
            const a = linesA[i];
            const b = linesB[i];
            if (a === b) {
              return (
                <div key={i} className="px-4 py-0.5 text-gray-600">
                  {" "}
                  {a}
                </div>
              );
            }
            return (
              <div key={i}>
                {a !== undefined && (
                  <div className="px-4 py-0.5 bg-red-50 text-red-800">
                    -{a}
                  </div>
                )}
                {b !== undefined && (
                  <div className="px-4 py-0.5 bg-green-50 text-green-800">
                    +{b}
                  </div>
                )}
              </div>
            );
          })}
        </pre>
      </div>
    </div>
  );
}
