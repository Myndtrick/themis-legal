"use client";

import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";

interface CategoryRow {
  id: number;
  slug: string;
  name_ro: string;
  name_en: string;
  description: string | null;
  group_name: string;
  group_slug: string;
  group_color: string;
  law_count: number;
}

export function CategoriesTable() {
  const [categories, setCategories] = useState<CategoryRow[]>([]);
  const [loading, setLoading] = useState(true);

  // Add subcategory form
  const [showForm, setShowForm] = useState(false);
  const [formGroup, setFormGroup] = useState("");
  const [formNameRo, setFormNameRo] = useState("");
  const [formNameEn, setFormNameEn] = useState("");
  const [formDesc, setFormDesc] = useState("");

  async function fetchCategories() {
    try {
      const data = await apiFetch<CategoryRow[]>("/api/settings/categories");
      setCategories(data);
    } catch { /* silent */ }
    setLoading(false);
  }

  useEffect(() => { fetchCategories(); }, []);

  async function handleAddSubcategory(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiFetch("/api/settings/categories/subcategory", {
        method: "POST",
        body: JSON.stringify({
          group_slug: formGroup,
          name_ro: formNameRo,
          name_en: formNameEn,
          description: formDesc,
        }),
      });
      setShowForm(false);
      setFormGroup("");
      setFormNameRo("");
      setFormNameEn("");
      setFormDesc("");
      fetchCategories();
    } catch { /* silent */ }
  }

  // Get unique groups for the dropdown
  const groupSlugs = [...new Set(categories.map((c) => c.group_slug))];

  if (loading) return <div className="text-gray-400 py-4">Loading categories...</div>;

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-lg font-semibold">Category Management</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700"
        >
          + Add subcategory
        </button>
      </div>

      {/* Add form */}
      {showForm && (
        <form onSubmit={handleAddSubcategory} className="mb-4 p-4 bg-gray-50 rounded-lg border space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Group</label>
              <select
                value={formGroup}
                onChange={(e) => setFormGroup(e.target.value)}
                required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
              >
                <option value="">Select group...</option>
                {groupSlugs.map((slug) => (
                  <option key={slug} value={slug}>
                    {categories.find((c) => c.group_slug === slug)?.group_name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Name (EN)</label>
              <input type="text" value={formNameEn} onChange={(e) => setFormNameEn(e.target.value)} required className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Name (RO)</label>
              <input type="text" value={formNameRo} onChange={(e) => setFormNameRo(e.target.value)} required className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Description</label>
              <input type="text" value={formDesc} onChange={(e) => setFormDesc(e.target.value)} className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
            </div>
          </div>
          <div className="flex gap-2">
            <button type="submit" className="text-sm bg-blue-600 text-white px-3 py-1.5 rounded-md">Save</button>
            <button type="button" onClick={() => setShowForm(false)} className="text-sm text-gray-600 px-3 py-1.5">Cancel</button>
          </div>
        </form>
      )}

      {/* Table */}
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-left">
            <tr>
              <th className="px-4 py-2.5 font-semibold text-gray-600">Group</th>
              <th className="px-4 py-2.5 font-semibold text-gray-600">Subcategory</th>
              <th className="px-4 py-2.5 font-semibold text-gray-600">Description</th>
              <th className="px-4 py-2.5 font-semibold text-gray-600 text-right">Laws</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {categories.map((c) => (
              <tr key={c.id} className={c.law_count === 0 ? "opacity-50" : ""}>
                <td className="px-4 py-2.5">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: c.group_color }} />
                    {c.group_name}
                  </span>
                </td>
                <td className="px-4 py-2.5">{c.name_en}</td>
                <td className="px-4 py-2.5 text-gray-500 text-xs">{c.description}</td>
                <td className="px-4 py-2.5 text-right">{c.law_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
