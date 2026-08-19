"use client";

import { useEffect, useRef, useState } from "react";

type ComboboxProps = {
  options: string[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
};

export function Combobox({ options, value, onChange, placeholder, required }: ComboboxProps) {
  const [query, setQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const filteredOptions = isOpen
    ? options.filter((option) => option.toLowerCase().includes(query.toLowerCase()))
    : options;

  useEffect(() => {
    if (!isOpen) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  const selectOption = (option: string) => {
    onChange(option);
    setQuery("");
    setIsOpen(false);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setIsOpen(true);
      setHighlightedIndex((index) => Math.min(index + 1, filteredOptions.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightedIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = filteredOptions[highlightedIndex];
      if (option) selectOption(option);
    } else if (event.key === "Escape") {
      setIsOpen(false);
      setQuery("");
    }
  };

  return (
    <div ref={containerRef} className="relative">
      <input
        required={required}
        value={isOpen ? query : value}
        onFocus={() => {
          setIsOpen(true);
          setQuery("");
          setHighlightedIndex(0);
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          setHighlightedIndex(0);
        }}
        onBlur={() => {
          setIsOpen(false);
          setQuery("");
        }}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="w-full rounded-md border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
      />
      {isOpen && filteredOptions.length > 0 && (
        <ul className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-md border border-zinc-300 bg-white text-sm shadow-lg dark:border-zinc-700 dark:bg-zinc-900">
          {filteredOptions.map((option, index) => (
            <li
              key={option}
              onMouseDown={(e) => {
                e.preventDefault();
                selectOption(option);
              }}
              onMouseEnter={() => setHighlightedIndex(index)}
              className={`cursor-pointer px-3 py-2 ${
                index === highlightedIndex
                  ? "bg-indigo-500 text-white"
                  : "text-zinc-900 dark:text-zinc-100"
              }`}
            >
              {option}
            </li>
          ))}
        </ul>
      )}
      {isOpen && filteredOptions.length === 0 && (
        <div className="absolute z-10 mt-1 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-500 shadow-lg dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400">
          No matches
        </div>
      )}
    </div>
  );
}
