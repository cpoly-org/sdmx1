import logging
from collections import ChainMap
from datetime import datetime, timedelta
from enum import Enum
from inspect import isclass
from typing import (
    Dict,
    Generic,
    Iterable,
    List,
    MutableMapping,
    Optional,
    Type,
    TypeVar,
    Union,
)

from sdmx.util import BaseModel, Field, compare, validator

from .internationalstring import InternationalString, _TInternationalStringInit

log = logging.getLogger(__name__)

# Utility classes not specified in the SDMX standard


class _MissingID(str):
    def __str__(self):
        return "(missing id)"

    def __eq__(self, other):
        return isinstance(other, self.__class__)


MissingID = _MissingID()


# §3.2: Base structures


class Annotation(BaseModel):
    #: Can be used to disambiguate multiple annotations for one AnnotableArtefact.
    id: Optional[str] = None
    #: Title, used to identify an annotation.
    title: Optional[str] = None
    #: Specifies how the annotation is processed.
    type: Optional[str] = None
    #: A link to external descriptive text.
    url: Optional[str] = None

    #: Content of the annotation.
    text: InternationalString = InternationalString()

    def __init__(self, *, text: _TInternationalStringInit = None, **kwargs):
        if text is not None:
            kwargs["text"] = InternationalString(text)
        super().__init__(**kwargs)


class AnnotableArtefact(BaseModel):
    #: :class:`Annotations <.Annotation>` of the object.
    #:
    #: :mod:`pandaSDMX` implementation: The IM does not specify the name of this
    #: feature.
    annotations: List[Annotation] = []

    def get_annotation(self, **attrib):
        """Return a :class:`Annotation` with given `attrib`, e.g. 'id'.

        If more than one `attrib` is given, all must match a particular annotation.

        Raises
        ------
        KeyError
            If there is no matching annotation.
        """
        for anno in self.annotations:
            if all(getattr(anno, key, None) == value for key, value in attrib.items()):
                return anno

        raise KeyError(attrib)

    def pop_annotation(self, **attrib):
        """Remove and return a :class:`Annotation` with given `attrib`, e.g. 'id'.

        If more than one `attrib` is given, all must match a particular annotation.

        Raises
        ------
        KeyError
            If there is no matching annotation.
        """
        for i, anno in enumerate(self.annotations):
            if all(getattr(anno, key, None) == value for key, value in attrib.items()):
                return self.annotations.pop(i)

        raise KeyError(attrib)


class IdentifiableArtefact(AnnotableArtefact):
    #: Unique identifier of the object.
    id: str = MissingID
    #: Universal resource identifier that may or may not be resolvable.
    uri: Optional[str] = None
    #: Universal resource name. For use in SDMX registries; all registered
    #: objects have a URN.
    urn: Optional[str] = None

    urn_group: Dict = dict()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.urn:
            import sdmx.urn

            self.urn_group = sdmx.urn.match(self.urn)

        try:
            if self.id not in (self.urn_group["item_id"] or self.urn_group["id"]):
                raise ValueError(f"ID {self.id} does not match URN {self.urn}")
        except KeyError:
            pass

    def __eq__(self, other):
        """Equality comparison.

        IdentifiableArtefacts can be compared to other instances. For convenience, a
        string containing the object's ID is also equal to the object.
        """
        if isinstance(other, self.__class__):
            return self.id == other.id
        elif isinstance(other, str):
            return self.id == other

    def compare(self, other, strict=True):
        """Return :obj:`True` if `self` is the same as `other`.

        Two IdentifiableArtefacts are the same if they have the same :attr:`id`,
        :attr:`uri`, and :attr:`urn`.

        Parameters
        ----------
        strict : bool, optional
            Passed to :func:`.compare`.
        """
        return (
            compare("id", self, other, strict)
            and compare("uri", self, other, strict)
            and compare("urn", self, other, strict)
        )

    def __hash__(self):
        return id(self) if self.id == MissingID else hash(self.id)

    def __lt__(self, other):
        return (
            self.id < other.id if isinstance(other, self.__class__) else NotImplemented
        )

    def __str__(self):
        return self.id

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.id}>"


class NameableArtefact(IdentifiableArtefact):
    #: Multi-lingual name of the object.
    name: InternationalString = InternationalString()
    #: Multi-lingual description of the object.
    description: InternationalString = InternationalString()

    def __init__(
        self,
        *,
        name: _TInternationalStringInit = None,
        description: _TInternationalStringInit = None,
        **kwargs,
    ):
        if name is not None:
            kwargs["name"] = InternationalString(name)
        if description is not None:
            kwargs["description"] = InternationalString(description)
        super().__init__(**kwargs)

    def compare(self, other, strict=True):
        """Return :obj:`True` if `self` is the same as `other`.

        Two NameableArtefacts are the same if:

        - :meth:`.IdentifiableArtefact.compare` is :obj:`True`, and
        - they have the same :attr:`name` and :attr:`description`.

        Parameters
        ----------
        strict : bool, optional
            Passed to :func:`.compare` and :meth:`.IdentifiableArtefact.compare`.
        """
        if not super().compare(other, strict):
            pass
        elif self.name != other.name:
            log.debug(
                f"Not identical: name <{repr(self.name)}> != <{repr(other.name)}>"
            )
        elif self.description != other.description:
            log.debug(
                f"Not identical: description <{repr(self.description)}> != "
                f"<{repr(other.description)}>"
            )
        else:
            return True
        return False

    def _repr_kw(self) -> MutableMapping[str, str]:
        name = self.name.localized_default()
        return dict(
            cls=self.__class__.__name__, id=self.id, name=f": {name}" if name else ""
        )

    def __repr__(self) -> str:
        return "<{cls} {id}{name}>".format(**self._repr_kw())


class VersionableArtefact(NameableArtefact):
    #: A version string following an agreed convention.
    version: Optional[str] = None
    #: Date from which the version is valid.
    valid_from: Optional[str] = None
    #: Date from which the version is superseded.
    valid_to: Optional[str] = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        try:
            if self.version and self.version != self.urn_group["version"]:
                raise ValueError(
                    f"Version {self.version} does not match URN {self.urn}"
                )
            else:
                self.version = self.urn_group["version"]
        except KeyError:
            pass

    def compare(self, other, strict=True):
        """Return :obj:`True` if `self` is the same as `other`.

        Two VersionableArtefacts are the same if:

        - :meth:`.NameableArtefact.compare` is :obj:`True`, and
        - they have the same :attr:`version`.

        Parameters
        ----------
        strict : bool, optional
            Passed to :func:`.compare` and :meth:`.NameableArtefact.compare`.
        """
        return super().compare(other, strict) and compare(
            "version", self, other, strict
        )

    def _repr_kw(self) -> MutableMapping[str, str]:
        return ChainMap(
            super()._repr_kw(),
            dict(version=f"({self.version})" if self.version else ""),
        )


class MaintainableArtefact(VersionableArtefact):
    #: True if the object is final; otherwise it is in a draft state.
    is_final: Optional[bool] = None
    #: :obj:`True` if the content of the object is held externally; i.e., not
    #: the current :class:`Message`.
    is_external_reference: Optional[bool] = None
    #: URL of an SDMX-compliant web service from which the object can be
    #: retrieved.
    service_url: Optional[str] = None
    #: URL of an SDMX-ML document containing the object.
    structure_url: Optional[str] = None
    #: Association to the Agency responsible for maintaining the object.
    maintainer: Optional["Agency"] = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        try:
            if self.maintainer and self.maintainer.id != self.urn_group["agency"]:
                raise ValueError(
                    f"Maintainer {self.maintainer} does not match URN {self.urn}"
                )
            else:
                self.maintainer = Agency(id=self.urn_group["agency"])
        except KeyError:
            pass

    def compare(self, other, strict=True):
        """Return :obj:`True` if `self` is the same as `other`.

        Two MaintainableArtefacts are the same if:

        - :meth:`.VersionableArtefact.compare` is :obj:`True`, and
        - they have the same :attr:`maintainer`.

        Parameters
        ----------
        strict : bool, optional
            Passed to :func:`.compare` and :meth:`.VersionableArtefact.compare`.
        """
        return super().compare(other, strict) and compare(
            "maintainer", self, other, strict
        )

    def _repr_kw(self) -> MutableMapping[str, str]:
        return ChainMap(
            super()._repr_kw(),
            dict(maint=f"{self.maintainer}:" if self.maintainer else ""),
        )

    def __repr__(self) -> str:
        return "<{cls} {maint}{id}{version}{name}>".format(**self._repr_kw())


# §3.4: Data Types


ActionType = Enum("ActionType", "delete replace append information")

ConstraintRoleType = Enum("ConstraintRoleType", "allowable actual")

# NB three diagrams in the spec show this enumeration containing 'gregorianYearMonth'
#    but not 'gregorianYear' or 'gregorianMonth'. The table in §3.6.3.3 Representation
#    Constructs does the opposite. One ESTAT query (via SGR) shows a real-world usage
#    of 'gregorianYear'; while one query shows usage of 'gregorianYearMonth'; so all
#    three are included.
FacetValueType = Enum(
    "FacetValueType",
    """string bigInteger integer long short decimal float double boolean uri count
    inclusiveValueRange alpha alphaNumeric numeric exclusiveValueRange incremental
    observationalTimePeriod standardTimePeriod basicTimePeriod gregorianTimePeriod
    gregorianYear gregorianMonth gregorianYearMonth gregorianDay reportingTimePeriod
    reportingYear reportingSemester reportingTrimester reportingQuarter reportingMonth
    reportingWeek reportingDay dateTime timesRange month monthDay day time duration
    keyValues identifiableReference dataSetReference""",
)

UsageStatus = Enum("UsageStatus", "mandatory conditional")


# §3.5: Item Scheme

IT = TypeVar("IT", bound="Item")


class Item(NameableArtefact, Generic[IT]):
    parent: Optional[Union[IT, "ItemScheme"]] = None
    child: List[IT] = []

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Add this Item as a child of its parent
        parent = kwargs.get("parent", None)
        if parent:
            parent.append_child(self)

        # Add this Item as a parent of its children
        for c in kwargs.get("child", []):
            self.append_child(c)

    def __contains__(self, item):
        """Recursive containment."""
        for c in self.child:
            if item == c or item in c:
                return True

    def __iter__(self, recurse=True):
        yield self
        for c in self.child:
            yield from iter(c)

    @property
    def hierarchical_id(self):
        """Construct the ID of an Item in a hierarchical ItemScheme.

        Returns, for example, 'A.B.C' for an Item with id 'C' that is the child of an
        item with id 'B', which is the child of a root Item with id 'A'.

        See also
        --------
        .ItemScheme.get_hierarchical
        """
        return (
            f"{self.parent.hierarchical_id}.{self.id}"
            if isinstance(self.parent, self.__class__)
            else self.id
        )

    def append_child(self, other: IT):
        if other not in self.child:
            self.child.append(other)
        other.parent = self

    def get_child(self, id) -> IT:
        """Return the child with the given *id*."""
        for c in self.child:
            if c.id == id:
                return c
        raise ValueError(id)

    def get_scheme(self):
        """Return the :class:`ItemScheme` to which the Item belongs, if any."""
        try:
            # Recurse
            return self.parent.get_scheme()
        except AttributeError:
            # Either this Item is a top-level Item whose .parent refers to the
            # ItemScheme, or it has no parent
            return self.parent


class ItemScheme(MaintainableArtefact, Generic[IT]):
    """SDMX-IM Item Scheme.

    The IM states that ItemScheme “defines a *set* of :class:`Items <.Item>`…” To
    simplify indexing/retrieval, this implementation uses a :class:`dict` for the
    :attr:`items` attribute, in which the keys are the :attr:`~.IdentifiableArtefact.id`
    of the Item.

    Because this may change in future versions of pandaSDMX, user code should not access
    :attr:`items` directly. Instead, use the :func:`getattr` and indexing features of
    ItemScheme, or the public methods, to access and manipulate Items:

    >>> foo = ItemScheme(id='foo')
    >>> bar = Item(id='bar')
    >>> foo.append(bar)
    >>> foo
    <ItemScheme: 'foo', 1 items>
    >>> (foo.bar is bar) and (foo['bar'] is bar) and (bar in foo)
    True

    """

    # TODO add delete()
    # TODO add sorting capability; perhaps sort when new items are inserted

    # NB the IM does not specify; this could be True by default, but would need to check
    # against the automatic construction in .reader.*.
    is_partial: Optional[bool] = None

    #: Members of the ItemScheme. Both ItemScheme and Item are abstract classes.
    #: Concrete classes are paired: for example, a :class:`.Codelist` contains
    #: :class:`Codes <.Code>`.
    items: Dict[str, IT] = {}

    # The type of the Items in the ItemScheme. This is necessary because the type hint
    # in the class declaration is static; not meant to be available at runtime.
    _Item: Type = Item

    @validator("items", pre=True)
    def convert_to_dict(cls, v):
        if isinstance(v, dict):
            return v
        return {i.id: i for i in v}

    # Convenience access to items
    def __getattr__(self, name: str) -> IT:
        # Provided to pass test_dsd.py
        try:
            return self.__getitem__(name)
        except KeyError:
            raise AttributeError(name)

    def __getitem__(self, name: str) -> IT:
        return self.items[name]

    def get_hierarchical(self, id: str) -> IT:
        """Get an Item by its :attr:`~.Item.hierarchical_id`."""
        if "." not in id:
            return self.items[id]
        else:
            for item in self.items.values():
                if item.hierarchical_id == id:
                    return item
        raise KeyError(id)

    def __contains__(self, item: Union[str, IT]) -> bool:
        """Check containment.

        No recursive search on children is performed as these are assumed to be included
        in :attr:`items`. Allow searching by Item or its id attribute.
        """
        if isinstance(item, str):
            return item in self.items
        return item in self.items.values()

    def __iter__(self):
        return iter(self.items.values())

    def extend(self, items: Iterable[IT]):
        """Extend the ItemScheme with members of `items`.

        Parameters
        ----------
        items : iterable of :class:`.Item`
            Elements must be of the same class as :attr:`items`.
        """
        for i in items:
            self.append(i)

    def __len__(self):
        return len(self.items)

    def append(self, item: IT):
        """Add *item* to the ItemScheme.

        Parameters
        ----------
        item : same class as :attr:`items`
            Item to add.
        """
        if item.id in self.items:
            raise ValueError(f"Item with id {repr(item.id)} already exists")
        self.items[item.id] = item
        if item.parent is None:
            item.parent = self

    def compare(self, other, strict=True):
        """Return :obj:`True` if `self` is the same as `other`.

        Two ItemSchemes are the same if:

        - :meth:`.MaintainableArtefact.compare` is :obj:`True`, and
        - their :attr:`items` have the same keys, and corresponding
          :class:`Items <Item>` compare equal.

        Parameters
        ----------
        strict : bool, optional
            Passed to :func:`.compare` and :meth:`.MaintainableArtefact.compare`.
        """
        if not super().compare(other, strict):
            pass
        elif set(self.items) != set(other.items):
            log.debug(
                f"ItemScheme contents differ: {repr(set(self.items))} != "
                + repr(set(other.items))
            )
        else:
            for id, item in self.items.items():
                if not item.compare(other.items[id], strict):
                    log.debug(f"…for items with id={repr(id)}")
                    return False
            return True

        return False

    def __repr__(self):
        return "<{cls} {maint}{id}{version} ({N} items){name}>".format(
            **self._repr_kw(), N=len(self.items)
        )

    def setdefault(self, obj=None, **kwargs) -> IT:
        """Retrieve the item *name*, or add it with *kwargs* and return it.

        The returned object is a reference to an object in the ItemScheme, and is of the
        appropriate class.
        """
        if obj and len(kwargs):
            raise ValueError(
                "cannot give both *obj* and keyword arguments to setdefault()"
            )

        if not obj:
            # Replace a string 'parent' ID with a reference to the object
            parent = kwargs.pop("parent", None)
            if isinstance(parent, str):
                kwargs["parent"] = self[parent]

            # Instantiate an object of the correct class
            obj = self._Item(**kwargs)

        try:
            # Add the object to the ItemScheme
            self.append(obj)
        except ValueError:
            pass  # Already present

        return obj


Item.update_forward_refs()

# §3.6: Structure


class FacetType(BaseModel):
    class Config:
        extra = "forbid"

    #:
    is_sequence: Optional[bool] = None
    #:
    min_length: Optional[int] = None
    #:
    max_length: Optional[int] = None
    #:
    min_value: Optional[float] = None
    #:
    max_value: Optional[float] = None
    #:
    start_value: Optional[float] = None
    #:
    end_value: Optional[str] = None
    #:
    interval: Optional[float] = None
    #:
    time_interval: Optional[timedelta] = None
    #:
    decimals: Optional[int] = None
    #:
    pattern: Optional[str] = None
    #:
    start_time: Optional[datetime] = None
    #:
    end_time: Optional[datetime] = None


class Facet(BaseModel):
    class Config:
        extra = "forbid"

    #:
    type: FacetType = FacetType()
    #:
    value: Optional[str] = None
    #:
    value_type: Optional[FacetValueType] = None


class Representation(BaseModel):
    class Config:
        extra = "forbid"

    #:
    enumerated: Optional[ItemScheme] = None
    #:
    non_enumerated: List[Facet] = []

    def __repr__(self):
        return "<{}: {}, {}>".format(
            self.__class__.__name__, self.enumerated, self.non_enumerated
        )


# §4.4: Concept Scheme


class ISOConceptReference(BaseModel):
    class Config:
        extra = "forbid"

    #:
    agency: str
    #:
    id: str
    #:
    scheme_id: str


class Concept(Item["Concept"]):
    #:
    core_representation: Optional[Representation] = None
    #:
    iso_concept: Optional[ISOConceptReference] = None


class ConceptScheme(ItemScheme[Concept]):
    _Item = Concept


# §4.5: Category Scheme


class Category(Item["Category"]):
    """SDMX-IM Category."""


class CategoryScheme(ItemScheme[Category]):
    _Item = Category


class Categorisation(MaintainableArtefact):
    #:
    category: Optional[Category] = None
    #:
    artefact: Optional[IdentifiableArtefact] = None


# §4.6: Organisations


class Contact(BaseModel):
    """Organization contact information.

    IMF is the only known data provider that returns messages with :class:`Contact`
    information. These differ from the IM in several ways. This class reflects these
    differences:

    - 'name' and 'org_unit' are InternationalString, instead of strings.
    - 'email' may be a list of e-mail addresses, rather than a single address.
    - 'uri' may be a list of URIs, rather than a single URI.
    """

    #:
    name: InternationalString = InternationalString()
    #:
    org_unit: InternationalString = InternationalString()
    #:
    telephone: Optional[str] = None
    #:
    responsibility: InternationalString = InternationalString()
    #:
    email: List[str] = Field(default_factory=list)
    #:
    uri: List[str] = Field(default_factory=list)

    def __init__(
        self,
        *,
        name: _TInternationalStringInit = None,
        org_unit: _TInternationalStringInit = None,
        responsibility: _TInternationalStringInit = None,
        **kwargs,
    ):
        if name is not None:
            kwargs["name"] = InternationalString(name)
        if org_unit is not None:
            kwargs["org_unit"] = InternationalString(org_unit)
        if responsibility is not None:
            kwargs["responsibility"] = InternationalString(responsibility)
        super().__init__(**kwargs)


class Organisation(Item["Organisation"]):
    #:
    contact: List[Contact] = []


class Agency(Organisation):
    pass


# DataProvider delayed until after ConstrainableArtefact, below


# Update forward references to 'Agency'
for cls in list(locals().values()):
    if isclass(cls) and issubclass(cls, MaintainableArtefact):
        cls.update_forward_refs()


class OrganisationScheme:
    """SDMX-IM abstract OrganisationScheme."""


class AgencyScheme(ItemScheme[Agency], OrganisationScheme):
    _Item = Agency


# DataProviderScheme delayed until after DataProvider, below
