export default function AssistantLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col" style={{ height: "calc(100vh - 4rem - 4rem)" }}>
      {children}
    </div>
  );
}
