#!/usr/bin/env bash
# Bash completion for ia-search / ia_search.py

_ia_search_complete() {
  local cur prev words cword
  COMPREPLY=()
  if command -v _init_completion >/dev/null 2>&1; then
    _init_completion -n : || return
  else
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
  fi

  local opts="
    -q --query
    --mediatype
    --rows
    --page
    --sort
    --order
    --list-sort-options
    --list-field-options
    --fields
    --print-url
    --iso
    --description-term
    --ext
    --no-human
    --hash
    --download
    --download-dir
    --file-contains
    --aria2-path
    --max-connections
    --no-aria2
    --verbose -v
    --long-columns
    --no-terminal-aware
    --date-before
    --date-after
  "

  local media_vals="software audio movies texts image data"
  local order_vals="asc desc"
  local sort_vals="
    downloads desc downloads asc
    week desc week asc
    month desc month asc
    year desc year asc
    publicdate desc publicdate asc
    date desc date asc
    titleSorter desc titleSorter asc
    creatorSorter desc creatorSorter asc
    identifier asc identifier desc
    avg_rating desc avg_rating asc
    item_size desc item_size asc
    random desc random asc
  "
  local hash_vals="sha1 md5"

  case "$prev" in
    -q|--query|--download-dir|--file-contains|--aria2-path|--description-term)
      return 0;;
    --rows|--page|--max-connections)
      COMPREPLY=( $(compgen -W "5 10 25 50 100" -- "$cur") ); return 0;;
    --mediatype)
      COMPREPLY=( $(compgen -W "$media_vals" -- "$cur") ); return 0;;
    --order)
      COMPREPLY=( $(compgen -W "$order_vals" -- "$cur") ); return 0;;
    --sort)
      COMPREPLY=( $(compgen -W "$sort_vals" -- "$cur") ); return 0;;
    --fields)
      local fields="identifier title creator date publicdate downloads mediatype item_size month week year language num_reviews subject publisher rights licenseurl"
      COMPREPLY=( $(compgen -W "$fields" -- "$cur") ); return 0;;
    --hash)
      COMPREPLY=( $(compgen -W "$hash_vals" -- "$cur") ); return 0;;
    --date-before|--date-after)
      COMPREPLY=( $(compgen -W "$(date +%Y-%m-%d)" -- "$cur") ); return 0;;
  esac

  if [[ "$cur" == -* ]]; then
    COMPREPLY=( $(compgen -W "$opts" -- "$cur") ); return 0
  fi
  return 0
}

complete -F _ia_search_complete ia-search
complete -F _ia_search_complete ia_search.py

