"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<string>("idle");
  const [docId, setDocId] = useState<number | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const validateAndSetFile = (selectedFile: File) => {
    if (!selectedFile.name.endsWith(".pdf")) {
      setError("Only PDF files are supported");
      return;
    }
    if (selectedFile.size > 50 * 1024 * 1024) {
      setError("File size must be less than 50MB");
      return;
    }
    setFile(selectedFile);
    setError(null);
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const pollStatus = async (documentId: number) => {
    setProcessing(true);
    setProgress("processing");

    const maxAttempts = 120; // 10 minutes max
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 5000)); // Poll every 5s

      try {
        const res = await fetch(
          `http://localhost:8000/api/documents/${documentId}`
        );
        const data = await res.json();

        if (data.status === "completed") {
          setProgress("completed");
          setProcessing(false);
          // Redirect after brief success display
          setTimeout(() => router.push(`/documents/${documentId}`), 1500);
          return;
        } else if (data.status === "error") {
          setProgress("error");
          setError(data.error_message || "Processing failed");
          setProcessing(false);
          return;
        }
        // Still processing, continue polling
      } catch {
        // Network error, keep trying
      }
    }

    setProgress("error");
    setError("Processing timed out");
    setProcessing(false);
  };

  const handleUpload = async () => {
    if (!file) return;

    setUploading(true);
    setError(null);
    setProgress("uploading");

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch(
        "http://localhost:8000/api/documents/upload",
        {
          method: "POST",
          body: formData,
        }
      );

      if (!response.ok) {
        const errData = await response.json().catch(() => null);
        throw new Error(errData?.detail || "Upload failed");
      }

      const data = await response.json();
      setDocId(data.id);
      setUploading(false);

      // Start polling for processing status
      pollStatus(data.id);
    } catch (err: any) {
      setError(err.message || "Failed to upload document. Please try again.");
      setUploading(false);
      setProgress("idle");
    }
  };

  const statusConfig: Record<string, { icon: string; text: string; color: string }> = {
    idle: { icon: "", text: "", color: "" },
    uploading: { icon: "📤", text: "Uploading document...", color: "text-blue-600" },
    processing: { icon: "⚙️", text: "Processing document with AI... This may take a few minutes.", color: "text-yellow-600" },
    completed: { icon: "✅", text: "Processing complete! Redirecting...", color: "text-green-600" },
    error: { icon: "❌", text: "Processing failed", color: "text-red-600" },
  };

  const status = statusConfig[progress] || statusConfig.idle;

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-0">
      <h1 className="text-3xl font-bold text-gray-900 mb-6">
        Upload Document
      </h1>

      <div className="bg-white shadow rounded-lg p-6">
        {/* Drag & Drop Zone */}
        <div
          className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
            dragActive
              ? "border-blue-500 bg-blue-50"
              : "border-gray-300 hover:border-gray-400"
          }`}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf"
            onChange={handleFileChange}
            className="hidden"
            id="file-upload"
            disabled={uploading || processing}
          />

          <label htmlFor="file-upload" className="cursor-pointer">
            <div className="text-gray-400 mb-4">
              <svg
                className="mx-auto h-12 w-12"
                stroke="currentColor"
                fill="none"
                viewBox="0 0 48 48"
              >
                <path
                  d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3.172-3.172a4 4 0 00-5.656 0L28 28M8 32l9.172-9.172a4 4 0 015.656 0L28 28m0 0l4 4m4-24h8m-4-4v8m-12 4h.02"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <p className="text-sm text-gray-600">
              {dragActive
                ? "Drop your PDF here"
                : "Click to upload or drag and drop"}
            </p>
            <p className="text-xs text-gray-500 mt-1">PDF files up to 50MB</p>
          </label>
        </div>

        {/* Selected File Info */}
        {file && (
          <div className="mt-4 p-4 bg-gray-50 rounded-lg flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-900">📄 {file.name}</p>
              <p className="text-xs text-gray-500">
                {(file.size / 1024 / 1024).toFixed(2)} MB
              </p>
            </div>
            {!uploading && !processing && (
              <button
                onClick={() => {
                  setFile(null);
                  setError(null);
                  if (inputRef.current) inputRef.current.value = "";
                }}
                className="text-gray-400 hover:text-red-500 text-sm"
              >
                Remove
              </button>
            )}
          </div>
        )}

        {/* Status Display */}
        {progress !== "idle" && (
          <div
            className={`mt-4 p-4 rounded-lg ${
              progress === "completed"
                ? "bg-green-50"
                : progress === "error"
                ? "bg-red-50"
                : "bg-blue-50"
            }`}
          >
            <div className="flex items-center space-x-3">
              <span className="text-xl">{status.icon}</span>
              <div className="flex-1">
                <p className={`text-sm font-medium ${status.color}`}>
                  {status.text}
                </p>
                {progress === "processing" && (
                  <div className="mt-2 w-full bg-gray-200 rounded-full h-2">
                    <div className="bg-blue-600 h-2 rounded-full animate-pulse w-3/4"></div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Error Display */}
        {error && progress !== "error" && (
          <div className="mt-4 p-4 bg-red-50 rounded-lg">
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}

        {/* Upload Button */}
        <div className="mt-6">
          <button
            onClick={handleUpload}
            disabled={!file || uploading || processing}
            className={`w-full py-3 px-4 rounded-lg font-medium transition-colors ${
              file && !uploading && !processing
                ? "bg-blue-600 text-white hover:bg-blue-700"
                : "bg-gray-300 text-gray-500 cursor-not-allowed"
            }`}
          >
            {uploading
              ? "Uploading..."
              : processing
              ? "Processing..."
              : "Upload & Process Document"}
          </button>
        </div>

        {/* Link to document if completed or processing */}
        {docId && (
          <div className="mt-4 text-center">
            <button
              onClick={() => router.push(`/documents/${docId}`)}
              className="text-sm text-blue-600 hover:text-blue-700"
            >
              View document details →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
