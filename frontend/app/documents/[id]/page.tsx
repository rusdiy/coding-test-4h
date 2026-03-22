"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";

interface DocumentDetail {
  id: number;
  filename: string;
  upload_date: string;
  status: string;
  error_message?: string;
  total_pages: number;
  text_chunks: number;
  images: Array<{
    id: number;
    url: string;
    page: number;
    caption?: string;
    width: number;
    height: number;
  }>;
  tables: Array<{
    id: number;
    url: string;
    page: number;
    caption?: string;
    rows: number;
    columns: number;
    data?: any;
  }>;
}

export default function DocumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDocument();
  }, [params.id]);

  // Auto-refresh while processing
  useEffect(() => {
    if (!document || document.status !== "processing") return;

    const interval = setInterval(async () => {
      try {
        const response = await fetch(
          `http://localhost:8000/api/documents/${params.id}`
        );
        const data = await response.json();
        setDocument(data);
        if (data.status !== "processing") {
          clearInterval(interval);
        }
      } catch {
        // ignore
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [document?.status, params.id]);

  const fetchDocument = async () => {
    try {
      const response = await fetch(
        `http://localhost:8000/api/documents/${params.id}`
      );
      const data = await response.json();
      setDocument(data);
    } catch (error) {
      console.error("Error fetching document:", error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="text-center py-12">
        <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-blue-600 border-r-transparent"></div>
        <p className="mt-2 text-gray-600">Loading document...</p>
      </div>
    );
  }

  if (!document) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-600">Document not found</p>
        <Link
          href="/"
          className="text-blue-600 hover:text-blue-700 mt-4 inline-block"
        >
          Back to documents
        </Link>
      </div>
    );
  }

  const statusStyles: Record<string, { bg: string; text: string; icon: string }> = {
    completed: { bg: "bg-green-100", text: "text-green-800", icon: "✅" },
    processing: { bg: "bg-yellow-100", text: "text-yellow-800", icon: "⚙️" },
    error: { bg: "bg-red-100", text: "text-red-800", icon: "❌" },
    pending: { bg: "bg-gray-100", text: "text-gray-800", icon: "⏳" },
  };

  const st = statusStyles[document.status] || statusStyles.pending;

  return (
    <div className="px-4 sm:px-0">
      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">
              📄 {document.filename}
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Uploaded: {new Date(document.upload_date).toLocaleDateString()}{" "}
              {new Date(document.upload_date).toLocaleTimeString()}
            </p>
          </div>
          <div className="flex space-x-3">
            {document.status === "completed" && (
              <Link
                href={`/chat?document=${document.id}`}
                className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
              >
                💬 Chat with Document
              </Link>
            )}
            <button
              onClick={() => router.push("/")}
              className="bg-gray-200 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-300 transition-colors"
            >
              ← Back
            </button>
          </div>
        </div>
      </div>

      {/* Status Card */}
      <div className="bg-white shadow rounded-lg p-6 mb-6">
        <h2 className="text-xl font-semibold mb-4">Processing Status</h2>

        {/* Status Badge */}
        <div className="mb-4">
          <span
            className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-semibold ${st.bg} ${st.text}`}
          >
            {st.icon} &nbsp;{document.status.charAt(0).toUpperCase() + document.status.slice(1)}
          </span>
          {document.status === "processing" && (
            <span className="ml-3 text-sm text-gray-500 animate-pulse">
              Processing... This may take a few minutes.
            </span>
          )}
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-gray-50 rounded-lg p-4">
            <p className="text-sm text-gray-500">Pages</p>
            <p className="text-2xl font-bold text-gray-900">
              {document.total_pages}
            </p>
          </div>
          <div className="bg-gray-50 rounded-lg p-4">
            <p className="text-sm text-gray-500">Text Chunks</p>
            <p className="text-2xl font-bold text-gray-900">
              {document.text_chunks}
            </p>
          </div>
          <div className="bg-gray-50 rounded-lg p-4">
            <p className="text-sm text-gray-500">Images</p>
            <p className="text-2xl font-bold text-gray-900">
              {document.images.length}
            </p>
          </div>
          <div className="bg-gray-50 rounded-lg p-4">
            <p className="text-sm text-gray-500">Tables</p>
            <p className="text-2xl font-bold text-gray-900">
              {document.tables.length}
            </p>
          </div>
        </div>

        {document.error_message && (
          <div className="mt-4 p-4 bg-red-50 rounded-lg border border-red-200">
            <p className="text-sm font-medium text-red-800">Error Details:</p>
            <p className="text-sm text-red-700 mt-1">
              {document.error_message}
            </p>
          </div>
        )}
      </div>

      {/* Images */}
      {document.images.length > 0 && (
        <div className="bg-white shadow rounded-lg p-6 mb-6">
          <h2 className="text-xl font-semibold mb-4">
            🖼️ Extracted Images ({document.images.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {document.images.map((image) => (
              <div
                key={image.id}
                className="border rounded-lg p-4 hover:shadow-md transition-shadow"
              >
                <img
                  src={`http://localhost:8000${image.url}`}
                  alt={image.caption || "Document image"}
                  className="w-full rounded mb-2"
                />
                <p className="text-sm text-gray-600">
                  {image.caption || `Image from page ${image.page}`}
                </p>
                <p className="text-xs text-gray-500">
                  Page {image.page} • {image.width}×{image.height}px
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tables */}
      {document.tables.length > 0 && (
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-xl font-semibold mb-4">
            📊 Extracted Tables ({document.tables.length})
          </h2>
          <div className="space-y-4">
            {document.tables.map((table) => (
              <div
                key={table.id}
                className="border rounded-lg p-4 hover:shadow-md transition-shadow"
              >
                <img
                  src={`http://localhost:8000${table.url}`}
                  alt={table.caption || "Document table"}
                  className="w-full rounded mb-2"
                />
                <p className="text-sm text-gray-600">
                  {table.caption || `Table from page ${table.page}`}
                </p>
                <p className="text-xs text-gray-500">
                  Page {table.page} • {table.rows} rows × {table.columns}{" "}
                  columns
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty state when processing */}
      {document.status === "processing" &&
        document.images.length === 0 &&
        document.tables.length === 0 && (
          <div className="bg-white shadow rounded-lg p-12 text-center">
            <div className="inline-block h-10 w-10 animate-spin rounded-full border-4 border-solid border-blue-600 border-r-transparent mb-4"></div>
            <p className="text-gray-600">
              Extracting content from your document...
            </p>
            <p className="text-sm text-gray-500 mt-1">
              This page will automatically update when processing is complete.
            </p>
          </div>
        )}
    </div>
  );
}
